"""
USDA FoodData Central API Integration for Peptide Tracker
Includes food search and barcode lookup functionality
"""

import os
import requests
from flask import jsonify, request
from functools import lru_cache

# Get API key from environment variable
USDA_API_KEY = os.getenv('USDA_API_KEY', 'DEMO_KEY')
USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"


def search_food(query, page_size=10):
    """
    Search for food items in USDA database
    
    Args:
        query: Search term (e.g., "chicken breast")
        page_size: Number of results to return (default 10)
    
    Returns:
        JSON response with food items and nutrition data
    """
    try:
        url = f"{USDA_BASE_URL}/foods/search"
        params = {
            "api_key": USDA_API_KEY,
            "query": query,
            "pageSize": page_size,
            "dataType": ["Branded", "Survey (FNDDS)", "SR Legacy"]
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Format the response for easier frontend consumption
        formatted_results = []
        
        for food in data.get('foods', []):
            food_item = {
                'fdcId': food.get('fdcId'),
                'description': food.get('description'),
                'brandOwner': food.get('brandOwner'),
                'dataType': food.get('dataType'),
                'servingSize': food.get('servingSize'),
                'servingSizeUnit': food.get('servingSizeUnit'),
                'nutrients': {}
            }
            
            # Extract key nutrients
            for nutrient in food.get('foodNutrients', []):
                nutrient_name = nutrient.get('nutrientName', '')
                nutrient_value = nutrient.get('value', 0)
                nutrient_unit = nutrient.get('unitName', '')
                
                # Map common nutrients
                if 'Energy' in nutrient_name or 'Calor' in nutrient_name:
                    food_item['nutrients']['calories'] = {
                        'value': nutrient_value,
                        'unit': nutrient_unit
                    }
                elif 'Protein' in nutrient_name:
                    food_item['nutrients']['protein'] = {
                        'value': nutrient_value,
                        'unit': nutrient_unit
                    }
                elif 'Carbohydrate' in nutrient_name and 'by difference' in nutrient_name:
                    food_item['nutrients']['carbs'] = {
                        'value': nutrient_value,
                        'unit': nutrient_unit
                    }
                elif 'Total lipid' in nutrient_name or 'Fat, total' in nutrient_name:
                    food_item['nutrients']['fat'] = {
                        'value': nutrient_value,
                        'unit': nutrient_unit
                    }
                elif 'Fiber' in nutrient_name:
                    food_item['nutrients']['fiber'] = {
                        'value': nutrient_value,
                        'unit': nutrient_unit
                    }
                elif 'Sugars' in nutrient_name and 'total' in nutrient_name.lower():
                    food_item['nutrients']['sugar'] = {
                        'value': nutrient_value,
                        'unit': nutrient_unit
                    }
            
            formatted_results.append(food_item)
        
        return {
            'success': True,
            'totalResults': data.get('totalHits', 0),
            'foods': formatted_results
        }
        
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f"API request failed: {str(e)}"
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Unexpected error: {str(e)}"
        }


def lookup_barcode(barcode):
    """
    Look up food by UPC/barcode
    
    Args:
        barcode: UPC barcode number (e.g., "041220576821")
    
    Returns:
        JSON response with food item details
    """
    try:
        # First, search by barcode in the database
        url = f"{USDA_BASE_URL}/foods/search"
        params = {
            "api_key": USDA_API_KEY,
            "query": barcode,
            "dataType": ["Branded"],
            "pageSize": 5
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Filter results to find exact barcode match
        for food in data.get('foods', []):
            if food.get('gtinUpc') == barcode:
                # Get detailed information for this food
                return get_food_details(food.get('fdcId'))
        
        # If no exact match, return first result
        if data.get('foods'):
            return get_food_details(data['foods'][0].get('fdcId'))
        
        return {
            'success': False,
            'error': 'No food found with that barcode'
        }
        
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f"Barcode lookup failed: {str(e)}"
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Unexpected error: {str(e)}"
        }


def get_food_details(fdc_id):
    """
    Get detailed nutrition information for a specific food
    
    Args:
        fdc_id: FoodData Central ID
    
    Returns:
        JSON response with complete nutrition data
    """
    try:
        url = f"{USDA_BASE_URL}/food/{fdc_id}"
        params = {
            "api_key": USDA_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        food = response.json()
        
        # Format detailed nutrition data
        nutrition_data = {
            'success': True,
            'fdcId': food.get('fdcId'),
            'description': food.get('description'),
            'brandOwner': food.get('brandOwner'),
            'brandName': food.get('brandName'),
            'ingredients': food.get('ingredients'),
            'servingSize': food.get('servingSize'),
            'servingSizeUnit': food.get('servingSizeUnit'),
            'householdServingFullText': food.get('householdServingFullText'),
            'barcode': food.get('gtinUpc'),
            'nutrients': {}
        }
        
        # Extract all nutrients
        for nutrient in food.get('foodNutrients', []):
            nutrient_name = nutrient.get('nutrient', {}).get('name', '')
            nutrient_value = nutrient.get('amount', 0)
            nutrient_unit = nutrient.get('nutrient', {}).get('unitName', '')
            
            nutrition_data['nutrients'][nutrient_name] = {
                'value': nutrient_value,
                'unit': nutrient_unit
            }
        
        return nutrition_data
        
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f"Failed to get food details: {str(e)}"
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Unexpected error: {str(e)}"
        }


# Flask route handlers
def register_nutrition_routes(app):
    """
    Register nutrition API routes with Flask app
    
    Usage:
        from nutrition_api import register_nutrition_routes
        register_nutrition_routes(app)
    """
    
    @app.route('/api/nutrition/search', methods=['GET'])
    def api_search_food():
        query = request.args.get('query', '')
        page_size = request.args.get('pageSize', 10, type=int)
        
        if not query:
            return jsonify({
                'success': False,
                'error': 'Query parameter is required'
            }), 400
        
        result = search_food(query, page_size)
        return jsonify(result)
    
    
    @app.route('/api/nutrition/barcode/<barcode>', methods=['GET'])
    def api_lookup_barcode(barcode):
        if not barcode:
            return jsonify({
                'success': False,
                'error': 'Barcode is required'
            }), 400
        
        result = lookup_barcode(barcode)
        return jsonify(result)
    
    
    @app.route('/api/nutrition/food/<int:fdc_id>', methods=['GET'])
    def api_get_food_details(fdc_id):
        result = get_food_details(fdc_id)
        return jsonify(result)


# For testing
if __name__ == "__main__":
    # Test search
    print("Testing food search...")
    result = search_food("chicken breast")
    print(f"Found {result.get('totalResults')} results")
    
    # Test barcode (Quest Protein Bar)
    print("\nTesting barcode lookup...")
    result = lookup_barcode("793573192523")
    if result.get('success'):
        print(f"Found: {result.get('description')}")
