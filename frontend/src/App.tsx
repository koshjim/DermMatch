import { useState, useEffect, useRef } from 'react'
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
  const label = score >= 75 ? 'Clean Score' : score >= 45 ? 'Moderate Score' : 'Caution Score'
  return <span className={`safety-badge safety-${level}`}>⬤ {label} ({Math.round(score)})</span>
}

function SafetyInfo({ product }: { product: Product }) {
  const score = Math.round(product.safety_score)
  const flaggedIngredients = product.flagged_ingredients ?? []
  const avoidedIngredients = product.avoided_ingredients ?? []

  let scoreReason = 'This product has a lower score because more flagged chemicals were detected.'
  if (score >= 75) {
    scoreReason = 'This product has a high score because fewer flagged chemicals were detected.'
  } else if (score >= 45) {
    scoreReason = 'This score is moderate because some flagged chemicals were detected.'
  }

  return (
    <details className="safety-info">
      <summary className="safety-badge-toggle" aria-label={`How clean score is calculated for ${product.name}`}>
        <SafetyBadge score={product.safety_score} />
      </summary>
      <div className="safety-info-panel">
        <p className="safety-info-title">How Clean Score Works:</p>
        <p>Each product's clean score starts at 100, then there are penalties for flagged chemicals found in its ingredient list (according to the California Proposition 65 guidelines)</p>
        <p>Keep in mind that the quantity of each flagged ingredient isn't considered in the score calculation.</p>
        {/* <p>Each ingredient you asked to avoid in your query subtracts an extra 10 points when present.</p> */}
        <p className="safety-info-reason">{scoreReason}</p>
        <p className="safety-info-stats">Flagged chemicals found: {flaggedIngredients.length}</p>
        <p className="safety-info-stats">Avoided ingredients matched: {avoidedIngredients.length}</p>
        {flaggedIngredients.length > 0 && (
          <p className="safety-info-list">Flagged: {flaggedIngredients.slice(0, 5).join(', ')}{flaggedIngredients.length > 5 ? ', ...' : ''}</p>
        )}
        {avoidedIngredients.length > 0 && (
          <p className="safety-info-list">Avoided matches: {avoidedIngredients.slice(0, 5).join(', ')}{avoidedIngredients.length > 5 ? ', ...' : ''}</p>
        )}
      </div>
    </details>
  )
}

function App(): JSX.Element {
  const [useLlm, setUseLlm] = useState<boolean | null>(null)
  const [searchInput, setSearchInput] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [hasSearched, setHasSearched] = useState<boolean>(false)
  const [isSearching, setIsSearching] = useState<boolean>(false)
  const [visibleCount, setVisibleCount] = useState<number>(24)
  const [products, setProducts] = useState<Product[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [filters, setFilters] = useState<Filters>({ category: '', minPrice: '', maxPrice: '', minRating: '', sortBy: 'relevance' })
  const latestRequestId = useRef<number>(0)

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(data => setUseLlm(data.use_llm))
    fetch('/api/categories').then(r => r.json()).then(setCategories)
  }, [])

  const runSearch = async (term: string, currentFilters: Filters): Promise<void> => {
    const trimmed = term.trim()
    if (trimmed === '') {
      setProducts([])
      setIsSearching(false)
      return
    }

    const requestId = ++latestRequestId.current
    const params = new URLSearchParams({ q: trimmed })
    if (currentFilters.category) params.set('category', currentFilters.category)
    if (currentFilters.minPrice) params.set('min_price', currentFilters.minPrice)
    if (currentFilters.maxPrice) params.set('max_price', currentFilters.maxPrice)
    if (currentFilters.minRating) params.set('min_rating', currentFilters.minRating)
    if (currentFilters.sortBy !== 'relevance') params.set('sort_by', currentFilters.sortBy)
    try {
      const response = await fetch(`/api/products/search?${params}`)
      if (!response.ok) {
        throw new Error(`Search request failed with status ${response.status}`)
      }
      const data: Product[] = await response.json()
      if (requestId === latestRequestId.current) {
        setProducts(data)
      }
    } catch {
      if (requestId === latestRequestId.current) {
        setProducts([])
      }
    } finally {
      if (requestId === latestRequestId.current) {
        setIsSearching(false)
      }
    }
  }

  const executeSearch = (term: string): void => {
    const trimmed = term.trim()
    latestRequestId.current += 1
    setVisibleCount(24)

    if (!trimmed) {
      setSearchTerm('')
      setIsSearching(false)
      setProducts([])
      return
    }

    setHasSearched(true)
    setSearchTerm(trimmed)
  }

  const handleSearchInputChange = (value: string): void => {
    setSearchInput(value)

    if (!value.trim()) {
      latestRequestId.current += 1
      setSearchTerm('')
      setIsSearching(false)
      setVisibleCount(24)
      setProducts([])
    }
  }

  const handleSearchSubmit = (): void => {
    executeSearch(searchInput)
  }

  const handleChatSearch = (value: string): void => {
    setSearchInput(value)
    executeSearch(value)
  }

  const handleFilterChange = (key: keyof Filters, value: string): void => {
    const newFilters = { ...filters, [key]: value }
    setFilters(newFilters)
  }

  useEffect(() => {
    const trimmed = searchTerm.trim()
    if (!trimmed) {
      return
    }

    setVisibleCount(24)
    setIsSearching(true)
    runSearch(trimmed, filters)
  }, [searchTerm, filters])

  if (useLlm === null) return <></>

  const visibleProducts = products.slice(0, visibleCount)
  const canShowMore = products.length > visibleCount
  const exampleQueries = [
    'face oil without titanium dioxide',
    'toner for dry, acne-prone skin',
    'moisturizer for eczema',
    'cleanser with niacinamide',
    'sunscreen safe for sensitive skin',
  ]
  const splitIndex = Math.ceil(exampleQueries.length / 2)
  const exampleQueryRows = [
    exampleQueries.slice(0, splitIndex),
    exampleQueries.slice(splitIndex),
  ].filter((row) => row.length > 0)

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
            value={searchInput}
            onChange={(e) => handleSearchInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleSearchSubmit()
              }
            }}
          />
          <button
            type="button"
            className="search-submit-button"
            onClick={(e) => {
              e.stopPropagation()
              handleSearchSubmit()
            }}
          >
            Search
          </button>
        </div>
        {/* <p className="search-hint">Try a query:</p> */}
        <div className="example-query-grid">
          {exampleQueryRows.map((row, rowIndex) => (
            <div key={rowIndex} className="example-query-row">
              {row.map((query) => (
                <button
                  key={query}
                  type="button"
                  className="example-query-pill"
                  onClick={() => {
                    setSearchInput(query)
                    executeSearch(query)
                  }}
                >
                  {query}
                </button>
              ))}
            </div>
          ))}
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
        {searchTerm.trim() && isSearching && (
          <p className="search-status">Searching...</p>
        )}
        {searchTerm.trim() && !isSearching && products.length > 0 && (
          <p className="result-count">{products.length} result{products.length !== 1 ? 's' : ''} for "{searchTerm}"</p>
        )}
        {searchTerm.trim() && !isSearching && products.length === 0 && (
          <div className="empty-state">
            <p>No products found for "{searchTerm}"</p>
            <p className="empty-hint">Try a different search term or adjust your filters.</p>
          </div>
        )}
        {visibleProducts.map((product, index) => (
          <div key={index} className={`product-item${product.out_of_stock ? ' out-of-stock' : ''}`}>

            {/* Top row: product name/brand + safety score */}
            <div className="card-header">
              <div>

                <div className="brand-safety-row">
                  <p className="product-brand">{product.brand}</p>
                  <div className="safety-score-group">
                    <SafetyInfo product={product} />
                  </div>
                </div>

                <div>
                  <h3 className="product-name">
                    {product.url ? <a href={product.url} target="_blank" rel="noreferrer">{product.name}</a> : product.name}
                  </h3>
                </div>

              </div>
            </div>

            {/* Unified pill row */}
            <div className="pill-row">
              <span className="badge badge-category">{product.category}</span>

              {/* Ingredient signals row */}
              {((product.good_ingredients?.length ?? 0) > 0 || (product.avoided_ingredients?.length ?? 0) > 0) && (
                <div className="ingredient-row">
                  {product.good_ingredients?.map((ing, i) => (
                    <span key={`good-${i}`} className="ing-tag ing-good">✓ {ing}</span>
                  ))}
                  {product.avoided_ingredients?.map((ing, i) => (
                    <span key={`avoided-${i}`} className="ing-tag ing-bad">✗ {ing}</span>
                  ))}
                </div>
              )}

            </div>

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

            
            {product.description && (
              <details className="description-dropdown">
                <summary>Description</summary>
                <p className="product-description">{product.description}</p>

                {/* SVD debug info */}
                {product.top_dimensions && (
                <div className="svd-debug">
                  <p className="svd-title">SVD Score: {product.svd_score?.toFixed(4)}</p>
                  
                  <p className="svd-section-label">▲ Top 5 Dimensions</p>
                  {product.top_dimensions.top.map((d, i) => (
                    <div key={i} className="svd-dim-row">
                      <span className="svd-dim-label">Dim {d.dim}</span>
                      <span className="svd-dim-contrib">+{d.contribution.toFixed(4)}</span>
                      <span className="svd-dim-terms">{d.top_terms.join(', ')}</span>
                    </div>
                  ))}

                  <p className="svd-section-label">▼ Bottom 5 Dimensions</p>
                  {product.top_dimensions.bottom.map((d, i) => (
                    <div key={i} className="svd-dim-row">
                      <span className="svd-neg">Dim {d.dim}</span>
                      <span className="svd-dim-contrib svd-neg">{d.contribution.toFixed(4)}</span>
                      <span className="svd-dim-terms">{d.top_terms.join(', ')}</span>
                    </div>
                  ))}
                </div>
              )}
              </details>
            )}

            {/* {product.description && (
              <details className="description-dropdown">
                <summary>Description</summary>
                <p className="product-description">{product.description}</p>
              </details>
            )} */}

            <div className="match-score-wrapper">
              <p className="match-score-label">Match Score: {product.score.toFixed(1)}%</p>
            </div>
          </div>
        ))}

        {searchTerm.trim() && !isSearching && canShowMore && (
          <button
            type="button"
            className="show-more-button"
            onClick={() => setVisibleCount((current) => current + 60)}
          >
            Show {products.length - visibleCount} more products
          </button>
        )}
      </div>

      {/* Chat (only when USE_LLM = True in routes.py) */}
      {useLlm && <Chat onSearchTerm={handleChatSearch} />}
    </div>
  )
}

export default App
