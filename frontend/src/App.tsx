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

function StarRating({ rating }: { rating: number }) {
  return (
    <span className="star-rating">
      {[1, 2, 3, 4, 5].map(i => (
        <span key={i} className={i <= Math.round(rating) ? 'star filled' : 'star'}>★</span>
      ))}
      <span className="rating-number">{rating?.toFixed(1)}</span>
    </span>
  )
}

function SafetyBadge({ score }: { score: number }) {
  const level = score >= 75 ? 'high' : score >= 45 ? 'medium' : 'low'
  const label = score >= 75 ? 'Clean' : score >= 45 ? 'Moderate' : 'Review'
  return <span className={`safety-badge safety-${level}`}>⬤ {label} ({Math.round(score)})</span>
}

function App(): JSX.Element {
  const [useLlm, setUseLlm] = useState<boolean | null>(null)
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [hasSearched, setHasSearched] = useState<boolean>(false)
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
    if (value.trim()) setHasSearched(true)
    await runSearch(value, filters)
  }

  const handleFilterChange = (key: keyof Filters, value: string): void => {
    const newFilters = { ...filters, [key]: value }
    setFilters(newFilters)
    runSearch(searchTerm, newFilters)
  }

  if (useLlm === null) return <></>

  return (
    <div className={`full-body-container ${useLlm ? 'llm-mode' : ''} ${hasSearched ? 'searching' : ''}`}>
      {/* Search bar (always shown) */}
      <div className="top-text">
        <h1>DermMatch</h1>
        <p className="landing-tagline">Find clean, safe skincare — powered by ingredients</p>
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
          <option value="price_asc">Sort: Price, Low → High</option>
          <option value="price_desc">Sort: Price, High → Low</option>
          <option value="rating">Sort: Highest Rated</option>
          <option value="safety">Sort: Safest First</option>
        </select>
      </div>

      {/* Search results (always shown) */}
      <div id="answer-box">
        {searchTerm.trim() && products.length > 0 && (
          <p className="result-count">{products.length} result{products.length !== 1 ? 's' : ''} for "{searchTerm}"</p>
        )}
        {searchTerm.trim() && products.length === 0 && (
          <div className="empty-state">
            <p>No products found for "{searchTerm}"</p>
            <p className="empty-hint">Try a different search term or adjust your filters.</p>
          </div>
        )}
        {products.map((product, index) => (
          <div key={index} className={`product-item${product.out_of_stock ? ' out-of-stock' : ''}`}>

            {/* Top row: name + safety badge */}
            <div className="card-header">
              <div>
                <h3 className="product-name">{product.name}</h3>
                <p className="product-brand">{product.brand}</p>
              </div>
              <SafetyBadge score={product.safety_score} />
            </div>

            {/* Status badges */}
            {/* <div className="badge-row"> */}
              {/* {product.is_new && <span className="badge badge-new">New</span>} */}
              {/* {product.sephora_exclusive && <span className="badge badge-exclusive">Sephora Exclusive</span>} */}
              {/* {product.limited_edition && <span className="badge badge-limited">Limited Edition</span>} */}
              {/* {product.out_of_stock && <span className="badge badge-oos">Out of Stock</span>} */}
              <span className="badge badge-category">{product.category}</span>
            {/* </div> */}

            {/* Rating + price row */}
            <div className="meta-row">
              <StarRating rating={product.rating} />
              {product.review_count > 0 && (
                <span className="review-count">{product.review_count.toLocaleString()} reviews</span>
              )}
              <span className="price-block">
                {product.sale_price && product.sale_price < product.price ? (
                  <>
                    <span className="price-original">${product.price?.toFixed(2)}</span>
                    <span className="price-sale">${product.sale_price.toFixed(2)}</span>
                  </>
                ) : (
                  <span className="price-regular">${product.price?.toFixed(2)}</span>
                )}
              </span>
            </div>

            {/* Highlights */}
            {product.highlights && (
              <div className="highlights-row">
                {product.highlights.split(',').map((h, i) => (
                  <span key={i} className="highlight-tag">{h.trim()}</span>
                ))}
                <span className="badge badge-category">{product.category}</span>
              </div>
              
            )}

            <p className="product-description">{product.description}</p>

            {/* Flagged ingredients */}
            {product.flagged_ingredients?.length > 0 && (
              <div className="flagged-block">
                <span className="flagged-label">⚠ Flagged ingredients: </span>
                {product.flagged_ingredients.map((ing, i) => (
                  <span key={i} className="flagged-tag">{ing}</span>
                ))}
              </div>
            )}

            <p className="match-score-label">Match: {(product.score * 100).toFixed(0)}%</p>
          </div>
        ))}
      </div>

      {/* Chat (only when USE_LLM = True in routes.py) */}
      {useLlm && <Chat onSearchTerm={handleSearch} />}
    </div>
  )
}

export default App
