import React, { useState, useEffect } from 'react';
import { Search, Barcode, X, Loader } from 'lucide-react';

const NutritionSearch = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedFood, setSelectedFood] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [barcodeInput, setBarcodeInput] = useState('');
  const [showBarcodeInput, setShowBarcodeInput] = useState(false);

  // Search for food
  const handleSearch = async (e) => {
    e?.preventDefault();
    if (!searchQuery.trim()) return;

    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/nutrition/search?query=${encodeURIComponent(searchQuery)}&pageSize=20`);
      const data = await response.json();
      
      if (data.success) {
        setSearchResults(data.foods);
      } else {
        setError(data.error || 'Failed to search foods');
      }
    } catch (err) {
      setError('Network error. Please try again.');
      console.error('Search error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Barcode lookup
  const handleBarcodeLookup = async (e) => {
    e?.preventDefault();
    if (!barcodeInput.trim()) return;

    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/nutrition/barcode/${barcodeInput}`);
      const data = await response.json();
      
      if (data.success) {
        setSelectedFood(data);
        setShowBarcodeInput(false);
        setBarcodeInput('');
      } else {
        setError(data.error || 'Barcode not found');
      }
    } catch (err) {
      setError('Network error. Please try again.');
      console.error('Barcode lookup error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Get detailed info for selected food
  const handleSelectFood = async (food) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/nutrition/food/${food.fdcId}`);
      const data = await response.json();
      
      if (data.success) {
        setSelectedFood(data);
      } else {
        // Fallback to basic info
        setSelectedFood(food);
      }
    } catch (err) {
      // Fallback to basic info
      setSelectedFood(food);
      console.error('Details error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Format nutrient value
  const formatNutrient = (nutrient) => {
    if (!nutrient) return 'N/A';
    return `${nutrient.value?.toFixed(1) || 0} ${nutrient.unit || ''}`;
  };

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h2 className="text-3xl font-bold mb-6 text-gray-800">Nutrition Search</h2>
        
        {/* Search Bar */}
        <div className="mb-6">
          <form onSubmit={handleSearch} className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-3 text-gray-400" size={20} />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search for food (e.g., chicken breast, apple, protein powder...)"
                className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Searching...' : 'Search'}
            </button>
            <button
              type="button"
              onClick={() => setShowBarcodeInput(!showBarcodeInput)}
              className="px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              title="Scan Barcode"
            >
              <Barcode size={20} />
            </button>
          </form>
        </div>

        {/* Barcode Input */}
        {showBarcodeInput && (
          <div className="mb-6 p-4 bg-green-50 rounded-lg border border-green-200">
            <form onSubmit={handleBarcodeLookup} className="flex gap-2">
              <input
                type="text"
                value={barcodeInput}
                onChange={(e) => setBarcodeInput(e.target.value)}
                placeholder="Enter barcode/UPC number"
                className="flex-1 px-4 py-2 border border-green-300 rounded-lg focus:ring-2 focus:ring-green-500"
              />
              <button
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400"
              >
                Lookup
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowBarcodeInput(false);
                  setBarcodeInput('');
                }}
                className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400"
              >
                Cancel
              </button>
            </form>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            {error}
          </div>
        )}

        {/* Loading Indicator */}
        {loading && (
          <div className="flex justify-center items-center py-12">
            <Loader className="animate-spin text-blue-600" size={40} />
          </div>
        )}

        {/* Search Results */}
        {!loading && searchResults.length > 0 && !selectedFood && (
          <div className="space-y-4">
            <h3 className="text-xl font-semibold text-gray-700">
              Found {searchResults.length} results
            </h3>
            <div className="grid gap-4">
              {searchResults.map((food) => (
                <div
                  key={food.fdcId}
                  onClick={() => handleSelectFood(food)}
                  className="p-4 border border-gray-200 rounded-lg hover:border-blue-500 hover:bg-blue-50 cursor-pointer transition-all"
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <h4 className="font-semibold text-gray-800">{food.description}</h4>
                      {food.brandOwner && (
                        <p className="text-sm text-gray-600 mt-1">{food.brandOwner}</p>
                      )}
                      {food.servingSize && (
                        <p className="text-sm text-gray-500 mt-1">
                          Serving: {food.servingSize} {food.servingSizeUnit}
                        </p>
                      )}
                    </div>
                    <div className="text-right ml-4">
                      {food.nutrients.calories && (
                        <div className="text-lg font-bold text-blue-600">
                          {formatNutrient(food.nutrients.calories)}
                        </div>
                      )}
                      <div className="text-xs text-gray-500 mt-1">
                        {food.dataType}
                      </div>
                    </div>
                  </div>
                  
                  {/* Quick nutrition preview */}
                  <div className="mt-3 flex gap-4 text-sm text-gray-600">
                    {food.nutrients.protein && (
                      <span>Protein: {formatNutrient(food.nutrients.protein)}</span>
                    )}
                    {food.nutrients.carbs && (
                      <span>Carbs: {formatNutrient(food.nutrients.carbs)}</span>
                    )}
                    {food.nutrients.fat && (
                      <span>Fat: {formatNutrient(food.nutrients.fat)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Selected Food Details */}
        {selectedFood && (
          <div className="border-2 border-blue-500 rounded-lg p-6">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-2xl font-bold text-gray-800">{selectedFood.description}</h3>
                {selectedFood.brandOwner && (
                  <p className="text-gray-600 mt-1">{selectedFood.brandOwner}</p>
                )}
                {selectedFood.barcode && (
                  <p className="text-sm text-gray-500 mt-1">Barcode: {selectedFood.barcode}</p>
                )}
              </div>
              <button
                onClick={() => {
                  setSelectedFood(null);
                  setSearchResults([]);
                }}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <X size={24} />
              </button>
            </div>

            {/* Serving Size */}
            {selectedFood.servingSize && (
              <div className="mb-4 p-3 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-600">Serving Size</p>
                <p className="text-lg font-semibold">
                  {selectedFood.servingSize} {selectedFood.servingSizeUnit}
                  {selectedFood.householdServingFullText && (
                    <span className="text-sm text-gray-600 ml-2">
                      ({selectedFood.householdServingFullText})
                    </span>
                  )}
                </p>
              </div>
            )}

            {/* Macros */}
            <div className="grid grid-cols-4 gap-4 mb-6">
              {selectedFood.nutrients?.['Energy']?.value && (
                <div className="text-center p-4 bg-blue-50 rounded-lg">
                  <div className="text-2xl font-bold text-blue-600">
                    {selectedFood.nutrients['Energy'].value.toFixed(0)}
                  </div>
                  <div className="text-sm text-gray-600">Calories</div>
                </div>
              )}
              {selectedFood.nutrients?.['Protein']?.value && (
                <div className="text-center p-4 bg-green-50 rounded-lg">
                  <div className="text-2xl font-bold text-green-600">
                    {selectedFood.nutrients['Protein'].value.toFixed(1)}g
                  </div>
                  <div className="text-sm text-gray-600">Protein</div>
                </div>
              )}
              {selectedFood.nutrients?.['Carbohydrate, by difference']?.value && (
                <div className="text-center p-4 bg-yellow-50 rounded-lg">
                  <div className="text-2xl font-bold text-yellow-600">
                    {selectedFood.nutrients['Carbohydrate, by difference'].value.toFixed(1)}g
                  </div>
                  <div className="text-sm text-gray-600">Carbs</div>
                </div>
              )}
              {selectedFood.nutrients?.['Total lipid (fat)']?.value && (
                <div className="text-center p-4 bg-red-50 rounded-lg">
                  <div className="text-2xl font-bold text-red-600">
                    {selectedFood.nutrients['Total lipid (fat)'].value.toFixed(1)}g
                  </div>
                  <div className="text-sm text-gray-600">Fat</div>
                </div>
              )}
            </div>

            {/* All Nutrients */}
            <div className="border-t pt-4">
              <h4 className="font-semibold text-gray-700 mb-3">Complete Nutrition Facts</h4>
              <div className="grid grid-cols-2 gap-3">
                {selectedFood.nutrients && Object.entries(selectedFood.nutrients).map(([name, data]) => (
                  <div key={name} className="flex justify-between p-2 bg-gray-50 rounded">
                    <span className="text-sm text-gray-700">{name}</span>
                    <span className="text-sm font-semibold text-gray-800">
                      {data.value?.toFixed(2)} {data.unit}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Ingredients */}
            {selectedFood.ingredients && (
              <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                <h4 className="font-semibold text-gray-700 mb-2">Ingredients</h4>
                <p className="text-sm text-gray-600">{selectedFood.ingredients}</p>
              </div>
            )}

            {/* Action Buttons */}
            <div className="mt-6 flex gap-3">
              <button className="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                Add to Meal Log
              </button>
              <button className="flex-1 px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
                Save to Favorites
              </button>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && searchResults.length === 0 && !selectedFood && !error && (
          <div className="text-center py-12 text-gray-500">
            <Search size={48} className="mx-auto mb-4 text-gray-300" />
            <p>Search for food items or scan a barcode to get started</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default NutritionSearch;
