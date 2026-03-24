import { useState, useEffect } from 'react'
import './App.css'
import SearchIcon from './assets/mag.png'
import { Product } from './types'
import Chat from './Chat'

interface Filters {
  category: string
  minPrice: string
  maxPrice: string
  minRating: string
  sortBy: string
}

function App(): JSX.Element {
  const [useLlm, setUseLlm] = useState<boolean | null>(null)
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [products, setProducts] = useState<Product[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [filters, setFilters] = useState<Filters>({ category: '', minPrice: '', maxPrice: '', minRating: '', sortBy: 'relevance' })

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(data => setUseLlm(data.use_llm))
    fetch('/api/categories').then(r => r.json()).then(setCategories)
  }, [])

  const runSearch = async (term: string, currentFilters: Filters): Promise<void> => {
    if (term.trim() === '') { setProducts([]); return }
    const params = new URLSearchParams({ q: term })
    if (currentFilters.category) params.set('category', currentFilters.category)
    if (currentFilters.minPrice) params.set('min_price', currentFilters.minPrice)
    if (currentFilters.maxPrice) params.set('max_price', currentFilters.maxPrice)
    if (currentFilters.minRating) params.set('min_rating', currentFilters.minRating)
    if (currentFilters.sortBy !== 'relevance') params.set('sort_by', currentFilters.sortBy)
    const response = await fetch(`/api/products/search?${params}`)
    const data: Product[] = await response.json()
    setProducts(data)
  }

  const handleSearch = async (value: string): Promise<void> => {
    setSearchTerm(value)
    await runSearch(value, filters)
  }

  const handleFilterChange = (key: keyof Filters, value: string): void => {
    const newFilters = { ...filters, [key]: value }
    setFilters(newFilters)
    runSearch(searchTerm, newFilters)
  }

  if (useLlm === null) return <></>

  return (
    <div className={`full-body-container ${useLlm ? 'llm-mode' : ''}`}>
      {/* Search bar (always shown) */}
      <div className="top-text">
        <h1> DermMatch Wahoo!</h1>
        <div className="input-box" onClick={() => document.getElementById('search-input')?.focus()}>
          <img src={SearchIcon} alt="search" />
          <input
            id="search-input"
            placeholder="Search for a Sephora Skincare product"
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Filters & sort */}
      <div className="filter-bar">
        <select value={filters.category} onChange={e => handleFilterChange('category', e.target.value)}>
          <option value="">All Categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <input type="number" placeholder="Min $" min={0} value={filters.minPrice} onChange={e => handleFilterChange('minPrice', e.target.value)} />
        <input type="number" placeholder="Max $" min={0} value={filters.maxPrice} onChange={e => handleFilterChange('maxPrice', e.target.value)} />
        <select value={filters.minRating} onChange={e => handleFilterChange('minRating', e.target.value)}>
          <option value="">Any Rating</option>
          <option value="3">3+ stars</option>
          <option value="3.5">3.5+ stars</option>
          <option value="4">4+ stars</option>
          <option value="4.5">4.5+ stars</option>
        </select>
        <select value={filters.sortBy} onChange={e => handleFilterChange('sortBy', e.target.value)}>
          <option value="relevance">Sort: Relevance</option>
          <option value="price_asc">Price: Low → High</option>
          <option value="price_desc">Price: High → Low</option>
          <option value="rating">Highest Rated</option>
          <option value="safety">Safest First</option>
        </select>
      </div>

      {/* Search results (always shown) */}
      <div id="answer-box">
        {products.map((product, index) => (
          <div key={index} className="product-item">
            <h3 className="product-name">{product.name}</h3>
            <p className="product-brand">{product.brand}</p>
            <p className="product-rating">Rating: {product.rating}</p>
            <p className="product-price">Price: ${product.price}</p>
            <p className="product-category">Category: {product.category}</p>
            <p className="product-description">{product.description}</p>
            <p className="match-score">Match Score: {product.score}</p>
            <p className="safety-score">Safety Score: {product.safety_score}</p>
            
            {product.flagged_ingredients?.length > 0 && (
            <p className="flagged-ingredients">
              Flagged Ingredients: {product.flagged_ingredients.join(', ')} </p>
          )}
          </div>
        ))}
      </div>

      {/* Chat (only when USE_LLM = True in routes.py) */}
      {useLlm && <Chat onSearchTerm={handleSearch} />}
    </div>
  )
}

export default App
