# ============================================================================
# ENHANCED SCANNING API ENDPOINTS
# Add these routes to your app.py (around line 2600 or after other routes)
# ============================================================================

@app.route("/api/classify-food", methods=["POST"])
@login_required
def api_classify_food():
    """Enhanced food classification with better AI prompts"""
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400
        
        file = request.files['image']
        if not file.filename:
            return jsonify({"error": "Empty filename"}), 400
        
        # Read and encode image
        import base64
        img_data = file.read()
        img_b64 = base64.b64encode(img_data).decode('utf-8')
        
        # Detect MIME type
        mime = file.content_type or 'image/jpeg'
        
        # Call OpenAI Vision with enhanced prompt
        result = _classify_food_enhanced(img_b64, mime)
        
        if result.get("error"):
            return jsonify({"error": result["error"]}), 500
        
        return jsonify({
            "predictions": result.get("predictions", []),
            "raw_response": result.get("raw_response", "")
        })
        
    except Exception as e:
        print(f"Food classification error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr-food", methods=["POST"])
@login_required
def api_ocr_food():
    """OCR for food labels/receipts"""
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400
        
        file = request.files['image']
        if not file.filename:
            return jsonify({"error": "Empty filename"}), 400
        
        import base64
        img_data = file.read()
        img_b64 = base64.b64encode(img_data).decode('utf-8')
        mime = file.content_type or 'image/jpeg'
        
        # Call OCR
        result = _ocr_text_extraction(img_b64, mime)
        
        if result.get("error"):
            return jsonify({"error": result["error"]}), 500
        
        return jsonify({
            "text": result.get("text", ""),
            "raw_response": result.get("raw_response", "")
        })
        
    except Exception as e:
        print(f"OCR error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/scan-peptide-label", methods=["POST"])
@login_required
def api_scan_peptide_label():
    """Scan peptide vial labels and match to known peptides"""
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400
        
        file = request.files['image']
        if not file.filename:
            return jsonify({"error": "Empty filename"}), 400
        
        import base64
        img_data = file.read()
        img_b64 = base64.b64encode(img_data).decode('utf-8')
        mime = file.content_type or 'image/jpeg'
        
        # Extract text
        ocr_result = _ocr_text_extraction(img_b64, mime)
        raw_text = ocr_result.get("text", "")
        
        # Match to known peptides
        peptides = _load_peptides_list()
        peptide_names = [p.get("name","") for p in peptides if p.get("name")]
        
        matches = _match_peptides_from_text(raw_text, peptide_names)
        
        return jsonify({
            "raw_text": raw_text,
            "matches": matches
        })
        
    except Exception as e:
        print(f"Peptide scan error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# ENHANCED AI HELPER FUNCTIONS
# Add these helper functions to your app.py
# ============================================================================

def _classify_food_enhanced(image_b64: str, mime_type: str = "image/jpeg") -> dict:
    """
    Enhanced food classification with better prompts for accuracy
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}
    
    # Enhanced prompt for better food recognition
    prompt = """Analyze this food image and identify what food items are visible.

INSTRUCTIONS:
1. Identify the PRIMARY food item(s) in the image
2. Be SPECIFIC (e.g., "Granny Smith Apple" not just "fruit")
3. If multiple items, list the most prominent ones
4. Give confidence scores (0.0-1.0)
5. Only include items you're confident about (>40% confidence)

Respond ONLY with valid JSON in this exact format:
{
  "predictions": [
    {"label": "Granny Smith Apple", "confidence": 0.95, "description": "Green apple variety"},
    {"label": "Red Delicious Apple", "confidence": 0.88, "description": "Red apple variety"}
  ]
}

DO NOT include any text before or after the JSON.
IMPORTANT: "label" should be a common food name that can be searched in USDA database."""
    
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o",  # Vision model
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_b64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.3
            },
            timeout=30
        )
        
        if resp.status_code != 200:
            return {"error": f"OpenAI API error: {resp.status_code}"}
        
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # Parse JSON response
        import json
        import re
        
        # Strip markdown code blocks if present
        content = re.sub(r'```json\s*|\s*```', '', content).strip()
        
        parsed = json.loads(content)
        predictions = parsed.get("predictions", [])
        
        # Sort by confidence
        predictions.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return {
            "predictions": predictions,
            "raw_response": content
        }
        
    except Exception as e:
        print(f"Food classification error: {e}")
        return {"error": str(e)}


def _ocr_text_extraction(image_b64: str, mime_type: str = "image/jpeg") -> dict:
    """
    Extract text from image using OpenAI Vision OCR
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}
    
    prompt = """Extract ALL text visible in this image.

INSTRUCTIONS:
1. Read every piece of text you can see
2. Preserve line breaks and structure
3. If it's a label, include product names, ingredients, nutrition facts
4. If it's a receipt, include items and quantities
5. If it's handwritten, do your best to decipher it

Return ONLY the extracted text, no explanations."""
    
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_b64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.1
            },
            timeout=30
        )
        
        if resp.status_code != 200:
            return {"error": f"OpenAI API error: {resp.status_code}"}
        
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        return {
            "text": content.strip(),
            "raw_response": content
        }
        
    except Exception as e:
        print(f"OCR error: {e}")
        return {"error": str(e)}


def _match_peptides_from_text(text: str, known_peptides: list) -> list:
    """
    Match extracted text to known peptide names using fuzzy matching
    """
    if not text or not known_peptides:
        return []
    
    text_lower = text.lower()
    matches = []
    
    for peptide in known_peptides:
        peptide_lower = peptide.lower()
        
        # Exact match
        if peptide_lower in text_lower:
            matches.append({
                "name": peptide,
                "confidence": 1.0,
                "match_type": "exact"
            })
            continue
        
        # Fuzzy match - check if significant portion matches
        # Simple algorithm: check character overlap
        peptide_chars = set(peptide_lower.replace("-", "").replace(" ", ""))
        text_chars = set(text_lower.replace("-", "").replace(" ", ""))
        
        if len(peptide_chars) > 0:
            overlap = len(peptide_chars & text_chars) / len(peptide_chars)
            
            # Also check if key parts of the name appear
            parts = peptide_lower.split("-")
            parts_found = sum(1 for p in parts if p in text_lower)
            parts_ratio = parts_found / len(parts) if parts else 0
            
            # Combined score
            score = (overlap * 0.4) + (parts_ratio * 0.6)
            
            if score > 0.5:  # 50% threshold
                matches.append({
                    "name": peptide,
                    "confidence": round(score, 2),
                    "match_type": "fuzzy"
                })
    
    # Sort by confidence
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    
    # Return top 5
    return matches[:5]
