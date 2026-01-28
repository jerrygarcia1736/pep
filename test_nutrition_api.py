#!/usr/bin/env python3
"""
Test script for USDA Nutrition API
Run this to verify your API key and connection are working
"""

import os
import sys
from nutrition_api import search_food, lookup_barcode, get_food_details

def print_separator():
    print("\n" + "="*70 + "\n")

def test_search():
    """Test food search functionality"""
    print("TEST 1: Searching for 'chicken breast'...")
    print_separator()
    
    result = search_food("chicken breast", page_size=5)
    
    if result.get('success'):
        print(f"✅ Search successful!")
        print(f"Found {result.get('totalResults')} total results")
        print(f"\nShowing first {len(result.get('foods', []))} results:\n")
        
        for i, food in enumerate(result.get('foods', [])[:3], 1):
            print(f"{i}. {food.get('description')}")
            if food.get('brandOwner'):
                print(f"   Brand: {food.get('brandOwner')}")
            
            nutrients = food.get('nutrients', {})
            if nutrients.get('calories'):
                cal = nutrients['calories']
                print(f"   Calories: {cal.get('value')} {cal.get('unit')}")
            if nutrients.get('protein'):
                prot = nutrients['protein']
                print(f"   Protein: {prot.get('value')} {prot.get('unit')}")
            print()
    else:
        print(f"❌ Search failed: {result.get('error')}")
        return False
    
    return True

def test_barcode():
    """Test barcode lookup functionality"""
    print_separator()
    print("TEST 2: Looking up barcode (Quest Protein Bar)...")
    print_separator()
    
    # Quest Protein Bar - Chocolate Chip Cookie Dough
    barcode = "793573192523"
    
    result = lookup_barcode(barcode)
    
    if result.get('success'):
        print(f"✅ Barcode lookup successful!")
        print(f"\nProduct: {result.get('description')}")
        if result.get('brandOwner'):
            print(f"Brand: {result.get('brandOwner')}")
        if result.get('servingSize'):
            print(f"Serving: {result.get('servingSize')} {result.get('servingSizeUnit')}")
        
        print("\nNutrition (per serving):")
        nutrients = result.get('nutrients', {})
        
        # Show main macros
        for nutrient_name in ['Energy', 'Protein', 'Carbohydrate, by difference', 'Total lipid (fat)']:
            if nutrient_name in nutrients:
                nut = nutrients[nutrient_name]
                display_name = nutrient_name.replace('Carbohydrate, by difference', 'Carbs').replace('Total lipid (fat)', 'Fat')
                print(f"  {display_name}: {nut.get('value')} {nut.get('unit')}")
    else:
        print(f"⚠️  Barcode lookup failed: {result.get('error')}")
        print("Note: Not all products have barcodes in USDA database")
        return True  # Don't fail the test - barcodes are hit or miss
    
    return True

def test_details():
    """Test getting detailed food information"""
    print_separator()
    print("TEST 3: Getting detailed food info (generic apple)...")
    print_separator()
    
    # FDC ID for generic apple
    fdc_id = 171688
    
    result = get_food_details(fdc_id)
    
    if result.get('success'):
        print(f"✅ Details lookup successful!")
        print(f"\nFood: {result.get('description')}")
        
        nutrients = result.get('nutrients', {})
        print(f"\nFound {len(nutrients)} nutrients")
        
        # Show some key nutrients
        print("\nKey nutrients per 100g:")
        for nutrient_name in ['Energy', 'Protein', 'Carbohydrate, by difference', 'Fiber, total dietary', 'Sugars, total including NLEA']:
            if nutrient_name in nutrients:
                nut = nutrients[nutrient_name]
                print(f"  {nutrient_name}: {nut.get('value')} {nut.get('unit')}")
    else:
        print(f"❌ Details lookup failed: {result.get('error')}")
        return False
    
    return True

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("  USDA NUTRITION API TEST SUITE")
    print("="*70)
    
    # Check for API key
    api_key = os.getenv('USDA_API_KEY', 'DEMO_KEY')
    print(f"\nAPI Key: {api_key[:10]}..." if len(api_key) > 10 else f"\nAPI Key: {api_key}")
    
    if api_key == 'DEMO_KEY':
        print("⚠️  Warning: Using DEMO_KEY (limited requests)")
        print("   Get a free API key at: https://fdc.nal.usda.gov/api-key-signup.html")
    else:
        print("✅ Using custom API key")
    
    # Run tests
    tests = [
        ("Food Search", test_search),
        ("Barcode Lookup", test_barcode),
        ("Food Details", test_details)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\n❌ {test_name} crashed: {str(e)}")
            results.append((test_name, False))
    
    # Print summary
    print_separator()
    print("TEST SUMMARY")
    print_separator()
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Your USDA API integration is working!")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
