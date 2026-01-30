"""
ADD THESE ROUTES TO YOUR EXISTING app.py

Insert these after your existing scan-food route (around line 750)
and before the scan-peptides route.

These routes add:
1. Camera-based food scanning with AI detection
2. Instant nutrition display using USDA API
3. Image upload handling
"""

import re
from werkzeug.utils import secure_filename
from PIL import Image
import io

# Add these configurations near the top of your app.py (after app = Flask(...))
# -----------------------------------------------------------------------------
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# API Configuration (add to your environment variables)
USDA_API_KEY = os.environ.get('USDA_API_KEY', 'eYtNAFd0hqr5U8W0DwOeZL2Kr9axdM1ehkSpVo5J')
CALORIENINJAS_API_KEY = os.environ.get('CALORIENINJAS_API_KEY', 'u8mlUxx0tzK4n4Q68DZkE5Ydn1s27VkEfY7L4o7L')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -----------------------------------------------------------------------------
# USDA Food Data Central API Helper
# -----------------------------------------------------------------------------
def search_usda_food(query: str, page_size: int = 5) -> dict:
    """
    Search USDA FoodData Central for food items
    Returns list of foods with nutrition data
    """
    if not USDA_API_KEY:
        return {'error': 'USDA API key not configured'}
    
    try:
        url = 'https://api.nal.usda.gov/fdc/v1/foods/search'
        params = {
            'api_key': USDA_API_KEY,
            'query': query,
            'pageSize': page_size,
            'dataType': ['Foundation', 'SR Legacy']  # Most reliable data types
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return {'error': f'USDA API error: {response.status_code}'}
        
        data = response.json()
        foods = data.get('foods', [])
        
        # Process and simplify the food data
        results = []
        for food in foods:
            # Extract nutrition from foodNutrients array
            nutrients = {n['nutrientName']: n.get('value', 0) 
                        for n in food.get('foodNutrients', [])}
            
            # Common nutrient mappings
            food_item = {
                'description': food.get('description', 'Unknown'),
                'fdcId': food.get('fdcId'),
                'calories': nutrients.get('Energy', 0),
                'protein': nutrients.get('Protein', 0),
                'carbs': nutrients.get('Carbohydrate, by difference', 0),
                'fat': nutrients.get('Total lipid (fat)', 0),
                'fiber': nutrients.get('Fiber, total dietary', 0),
                'sugar': nutrients.get('Sugars, total including NLEA', 0),
                'serving_size': '100g',  # USDA data is per 100g
                'data_type': food.get('dataType', 'Unknown')
            }
            results.append(food_item)
        
        return {'foods': results, 'total': data.get('totalHits', 0)}
    
    except requests.exceptions.Timeout:
        return {'error': 'USDA API timeout'}
    except Exception as e:
        return {'error': f'USDA API error: {str(e)}'}


def get_usda_food_details(fdc_id: int) -> dict:
    """Get detailed nutrition info for a specific food by FDC ID"""
    if not USDA_API_KEY:
        return {'error': 'USDA API key not configured'}
    
    try:
        url = f'https://api.nal.usda.gov/fdc/v1/food/{fdc_id}'
        params = {'api_key': USDA_API_KEY}
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return {'error': f'USDA API error: {response.status_code}'}
        
        food = response.json()
        
        # Extract all nutrients
        nutrients = {n['nutrient']['name']: n.get('amount', 0) 
                    for n in food.get('foodNutrients', [])}
        
        return {
            'description': food.get('description'),
            'calories': nutrients.get('Energy', 0),
            'protein': nutrients.get('Protein', 0),
            'carbs': nutrients.get('Carbohydrate, by difference', 0),
            'fat': nutrients.get('Total lipid (fat)', 0),
            'fiber': nutrients.get('Fiber, total dietary', 0),
            'sugar': nutrients.get('Sugars, total including NLEA', 0),
            'nutrients': nutrients
        }
    
    except Exception as e:
        return {'error': str(e)}


# -----------------------------------------------------------------------------
# CalorieNinjas API Helper (backup/alternative)
# -----------------------------------------------------------------------------
def search_calorieninjas_food(query: str) -> dict:
    """
    Search CalorieNinjas for food nutrition data
    Good for common foods and branded items
    """
    if not CALORIENINJAS_API_KEY:
        return {'error': 'CalorieNinjas API key not configured'}
    
    try:
        url = 'https://api.calorieninjas.com/v1/nutrition'
        params = {'query': query}
        headers = {'X-Api-Key': CALORIENINJAS_API_KEY}
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return {'error': f'CalorieNinjas API error: {response.status_code}'}
        
        data = response.json()
        items = data.get('items', [])
        
        # Convert to our standard format
        results = []
        for item in items:
            results.append({
                'description': item.get('name', ''),
                'calories': item.get('calories', 0),
                'protein': item.get('protein_g', 0),
                'carbs': item.get('carbohydrates_total_g', 0),
                'fat': item.get('fat_total_g', 0),
                'fiber': item.get('fiber_g', 0),
                'sugar': item.get('sugar_g', 0),
                'serving_size': f"{item.get('serving_size_g', 100)}g"
            })
        
        return {'foods': results, 'total': len(results)}
    
    except Exception as e:
        return {'error': str(e)}


# -----------------------------------------------------------------------------
# NEW ROUTE: Camera Food Scanner with Instant Nutrition
# -----------------------------------------------------------------------------
@app.route("/scan-food", methods=["GET"])
@login_required
def scan_food():
    """
    Camera-enabled food scanner
    Replaces the old scan_food route
    """
    return render_template("scan_food.html", title="Scan Food")


@app.route("/api/scan-food-image", methods=["POST"])
@login_required
def api_scan_food_image():
    """
    Handle food image upload, detect food, and return nutrition instantly
    
    Flow:
    1. Receive image upload
    2. Use OpenAI Vision to identify food
    3. Query USDA API for nutrition data
    4. Return combined result with instant macros
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Use JPG, PNG, or WEBP'}), 400
    
    try:
        # Read and validate image
        image_data = file.read()
        
        if len(image_data) > MAX_IMAGE_SIZE:
            return jsonify({'error': 'Image too large (max 10MB)'}), 400
        
        # Validate it's actually an image
        try:
            img = Image.open(io.BytesIO(image_data))
            img.verify()
        except Exception:
            return jsonify({'error': 'Invalid image file'}), 400
        
        # Convert to base64 for OpenAI
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        # Step 1: Identify food using OpenAI Vision
        food_detection = _openai_identify_food_from_image(image_b64)
        
        if 'error' in food_detection:
            return jsonify({
                'error': 'Food detection failed',
                'details': food_detection.get('error')
            }), 500
        
        detected_food_name = food_detection.get('name', '')
        confidence = food_detection.get('confidence', 0)
        alternatives = food_detection.get('alternatives', [])
        notes = food_detection.get('notes', '')
        
        if not detected_food_name:
            return jsonify({
                'error': 'Could not identify food in image',
                'raw_response': food_detection
            }), 400
        
        # Step 2: Search nutrition databases
        # Try USDA first (most reliable)
        usda_results = search_usda_food(detected_food_name, page_size=3)
        
        # Try CalorieNinjas as backup
        ninja_results = search_calorieninjas_food(detected_food_name)
        
        # Combine results
        all_foods = []
        
        # Add USDA results
        if 'foods' in usda_results:
            for food in usda_results['foods']:
                food['source'] = 'USDA'
                all_foods.append(food)
        
        # Add CalorieNinjas results
        if 'foods' in ninja_results:
            for food in ninja_results['foods']:
                food['source'] = 'CalorieNinjas'
                all_foods.append(food)
        
        if not all_foods:
            return jsonify({
                'error': 'No nutrition data found',
                'detected_food': detected_food_name,
                'confidence': confidence,
                'alternatives': alternatives
            }), 404
        
        # Step 3: Return results with instant nutrition
        return jsonify({
            'success': True,
            'detected_food': detected_food_name,
            'confidence': confidence,
            'alternatives': alternatives,
            'notes': notes,
            'foods': all_foods[:5],  # Return top 5 matches
            'total_results': len(all_foods)
        })
    
    except Exception as e:
        return jsonify({
            'error': 'Server error processing image',
            'details': str(e)
        }), 500


@app.route("/api/nutrition-search", methods=["GET"])
@login_required
def api_nutrition_search():
    """
    Manual nutrition search endpoint
    Used for text-based food lookups
    """
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({'error': 'No search query provided'}), 400
    
    # Search both APIs
    usda_results = search_usda_food(query, page_size=10)
    ninja_results = search_calorieninjas_food(query)
    
    all_foods = []
    
    if 'foods' in usda_results:
        for food in usda_results['foods']:
            food['source'] = 'USDA'
            all_foods.append(food)
    
    if 'foods' in ninja_results:
        for food in ninja_results['foods']:
            food['source'] = 'CalorieNinjas'
            all_foods.append(food)
    
    return jsonify({
        'success': True,
        'query': query,
        'foods': all_foods,
        'total': len(all_foods)
    })


@app.route("/api/log-food-entry", methods=["POST"])
@login_required
def api_log_food_entry():
    """
    Save food log entry to database
    Called after user confirms food selection
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    description = data.get('description', '')
    foods = data.get('foods', [])
    
    if not description and not foods:
        return jsonify({'error': 'No food information provided'}), 400
    
    # Calculate totals
    total_calories = sum(f.get('calories', 0) * f.get('quantity', 1) for f in foods)
    total_protein = sum(f.get('protein', 0) * f.get('quantity', 1) for f in foods)
    total_carbs = sum(f.get('carbs', 0) * f.get('quantity', 1) for f in foods)
    total_fat = sum(f.get('fat', 0) * f.get('quantity', 1) for f in foods)
    
    # Create food log entry
    db = get_session(db_url)
    try:
        food_log = FoodLog(
            user_id=session['user_id'],
            description=description or ', '.join([f.get('description', '') for f in foods]),
            total_calories=total_calories,
            total_protein_g=total_protein,
            total_carbs_g=total_carbs,
            total_fat_g=total_fat,
            raw_data=json.dumps(foods)
        )
        
        db.add(food_log)
        db.commit()
        
        return jsonify({
            'success': True,
            'message': 'Food logged successfully',
            'log_id': food_log.id,
            'totals': {
                'calories': round(total_calories, 1),
                'protein': round(total_protein, 1),
                'carbs': round(total_carbs, 1),
                'fat': round(total_fat, 1)
            }
        })
    
    except Exception as e:
        db.rollback()
        return jsonify({
            'error': 'Failed to save food log',
            'details': str(e)
        }), 500
    finally:
        db.close()


# Add this helper function to your existing nutrition route to display camera option
# Update your existing /nutrition route around line 1800-1900 to include scan button
