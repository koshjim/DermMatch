import { useState, useEffect, useRef } from 'react'
import React from 'react';
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

interface SearchSummaryResponse {
  summary: string
  sources: Array<{
    id: number | null
    name: string
    brand: string
    url: string | null
  }>
  total_results: number
  used_llm: boolean
}

interface ExpandedSearchResponse {
  original_query: string
  rag_query: string
  results: Product[]
}

const QUERY_DICTIONARY = [
  'moisturizer',
  'cleanser',
  'sunscreen',
  'toner',
  'serum',
  'mask',
  'exfoliator',
  'eczema',
  'acne',
  'sensitive',
  'niacinamide',
  'retinol',
  'hyaluronic',
  'hydrating',
  'face',
  'oil',
  'dry',
  'skin',
  "fine",
  "lines",
  "dark",
  "circles",
  "pores",
  "perfume"
]
const CATEGORY_MAP: Record<string, string> = {
  'face wash facial cleanser': 'Cleansers',
  'cleansing oil face oil': 'Cleansing Oils',
  'body lotion body oil': 'Moisturizers',
  'face creams': 'Moisturizers',
  'facial toner skin toner': 'Toners',
  'eye cream dark circles': 'Eye Creams',
  'facial peels': 'Exfoliators',
  'exfoliating scrub exfoliator': 'Exfoliators',
  'peels pads': 'Exfoliators',
  'facial treatment masks': 'Masks',
  'sheet masks': 'Masks',
  'face serum': 'Serums',
  'face sunscreen': 'Sunscreens',
  'lip balm lip care': 'Lip Treatments',
  'mini skincare': 'Mini Skincare'
}

function normalizeCategory(raw: string): string {
  return CATEGORY_MAP[raw.trim().toLowerCase()] ?? raw
}

const CANONICAL_CATEGORIES = [
  'Cleansers',
  'Cleansing Oils',
  'Moisturizers',
  'Toners',
  'Eye Creams',
  'Exfoliators',
  'Masks',
  'Serums',
  'Sunscreens',
  'Lip Treatments',
  'Mini Skincare'
]



function levenshteinDistance(left: string, right: string): number {
  if (left === right) return 0
  if (!left.length) return right.length
  if (!right.length) return left.length

  const matrix: number[][] = Array.from({ length: left.length + 1 }, () => Array(right.length + 1).fill(0))
  for (let i = 0; i <= left.length; i += 1) matrix[i][0] = i
  for (let j = 0; j <= right.length; j += 1) matrix[0][j] = j

  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      const substitutionCost = left[i - 1] === right[j - 1] ? 0 : 1
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + substitutionCost,
      )
    }
  }

  return matrix[left.length][right.length]
}

function getSuggestedQuery(query: string, products: Product[]): string | null {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return null

  const knownBrands = Array.from(new Set(
    products.map(p => p.brand?.trim().toLowerCase()).filter(Boolean)
  ))

  const tokens = normalized.split(/\s+/)
  const isKnownBrand = knownBrands.some(brand => {
    if (normalized.startsWith(brand)) return true
    if (levenshteinDistance(normalized, brand) <= 2) return true
    // Check if the query starts with something close to a brand name
    const queryPrefix = normalized.split(' ').slice(0, brand.split(' ').length).join(' ')
    return levenshteinDistance(queryPrefix, brand) <= 1
  })


  if (isKnownBrand) return null

  let changed = false

  const corrected = tokens.map((token) => {
    if (token.length <= 4 || QUERY_DICTIONARY.includes(token)) {
      return token
    }

    let bestCandidate = token
    let bestDistance = Number.POSITIVE_INFINITY

    for (const candidate of QUERY_DICTIONARY) {
      const distance = levenshteinDistance(token, candidate)
      if (distance < bestDistance) {
        bestDistance = distance
        bestCandidate = candidate
      }
    }

    if (bestDistance <= 2 && bestCandidate !== token) {
      changed = true
      return bestCandidate
    }
    return token
  })

  const suggestion = corrected.join(' ')
  return changed && suggestion !== normalized ? suggestion : null
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
  return <span className={`safety-badge safety-${level}`}>{label} ({Math.round(score)})  ⓘ </span>
}

function getSimilarProducts(
  product: Product,
  allProducts: Product[]
): { id: number; name: string; brand: string; score: number }[] {
  if (!product.top_dimensions || allProducts.length <= 1) return [];
  const dims = product.top_dimensions.top.map(d => d.contribution);
  const sims = allProducts
    .filter(p => p.id !== product.id && p.top_dimensions)
    .map(p => {
      const otherDims = p.top_dimensions!.top.map(d => d.contribution);
      const len = Math.min(dims.length, otherDims.length);
      const a = dims.slice(0, len);
      const b = otherDims.slice(0, len);
      const dot = a.reduce((sum, v, i) => sum + v * b[i], 0);
      const normA = Math.sqrt(a.reduce((sum, v) => sum + v * v, 0));
      const normB = Math.sqrt(b.reduce((sum, v) => sum + v * v, 0));
      const sim = normA && normB ? dot / (normA * normB) : 0;
      return { id: p.id, name: p.name, brand: p.brand, score: sim };
    });
  sims.sort((a, b) => b.score - a.score);
  return sims.slice(0, 3);
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
        {/* <p>Each ingredient you asked to avoid in your query subtracts an extra 10 points when present.</p> */}
        <p className="safety-info-reason">{scoreReason}</p>
        <p >Flagged chemicals found: {flaggedIngredients.length}</p>
        {flaggedIngredients.length > 0 && (
          <p className="safety-info-list">Flagged: {flaggedIngredients.slice(0, 5).join(', ')}{flaggedIngredients.length > 5 ? ', ...' : ''}</p>
        )}
        <p >Avoided ingredients matched: {avoidedIngredients.length}</p>
        {avoidedIngredients.length > 0 && (
          <p className="safety-info-list">Avoided matches: {avoidedIngredients.slice(0, 5).join(', ')}{avoidedIngredients.length > 5 ? ', ...' : ''}</p>
        )}
        <p className="safety-info-title">How Clean Score Works:</p>
        <p>Each product's clean score starts at 100, then there are penalties for flagged chemicals found in its ingredient list (according to the California Proposition 65 guidelines)</p>
        <p>Keep in mind that the quantity of each flagged ingredient isn't considered in the score calculation.</p>
      </div>
    </details>
  )
}

function renderWithBold(text: string): React.ReactNode {
  const parts = text.split(/(\*\*.*?\*\*)/g)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part
  )
}

function App(): JSX.Element {
  const [useLlm, setUseLlm] = useState<boolean | null>(null)
  const [useRag, setUseRag] = useState<boolean>(true)
  const [ingredientInput, setIngredientInput] = useState('')
  const [includeIngredients, setIncludeIngredients] = useState<string[]>([])
  const [excludeIngredients, setExcludeIngredients] = useState<string[]>([])
  const [searchInput, setSearchInput] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [hasSearched, setHasSearched] = useState<boolean>(false)
  const [isSearching, setIsSearching] = useState<boolean>(false)
  const [isRefining, setIsRefining] = useState<boolean>(false)
  const [visibleCount, setVisibleCount] = useState<number>(24)
  const [products, setProducts] = useState<Product[]>([])
  const [summaryText, setSummaryText] = useState<string>('')
  const [summarySources, setSummarySources] = useState<SearchSummaryResponse['sources']>([])
  const [isSummaryLoading, setIsSummaryLoading] = useState<boolean>(false)
  const [summaryError, setSummaryError] = useState<string>('')
  const [categories, setCategories] = useState<string[]>([])
  const [filters, setFilters] = useState<Filters>({ category: '', minPrice: '', maxPrice: '', minRating: '', sortBy: 'relevance' })
  const latestRequestId = useRef<number>(0)
  const [expandedQuery, setExpandedQuery] = useState<string>('')
  const [ingredientMode, setIngredientMode] = useState<'include' | 'exclude'>('include');

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(data => setUseLlm(data.use_llm))
    setCategories(CANONICAL_CATEGORIES)
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
    if (currentFilters.category) {
      const rawValue = Object.entries(CATEGORY_MAP).find(([, label]) => label === currentFilters.category)?.[0]
      params.set('category', rawValue ?? currentFilters.category)
    }
    if (currentFilters.minPrice) params.set('min_price', currentFilters.minPrice)
    if (currentFilters.maxPrice) params.set('max_price', currentFilters.maxPrice)
    if (currentFilters.minRating) params.set('min_rating', currentFilters.minRating)
    if (currentFilters.sortBy !== 'relevance') params.set('sort_by', currentFilters.sortBy)
    // Add RAG toggle
    params.set('use_rag', useRag ? 'true' : 'false')

    const runSummary = async (irResults: Product[]): Promise<void> => {
      if (!useLlm) {
        setSummaryText('')
        setSummarySources([])
        setSummaryError('')
        setIsSummaryLoading(false)
        return
      }

      setSummaryError('')
      setIsSummaryLoading(true)
      try {
        const summaryResponse = await fetch(`/api/products/summary?${params.toString()}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // Send only the fields the summary prompt needs; keeps the payload small.
            body: JSON.stringify({
              results: irResults.slice(0, 10).map(p => ({
                id: p.id,
                name: p.name,
                brand: p.brand,
                price: p.price,
                rating: p.rating,
                description: p.description,
                safety_score: p.safety_score,
                flagged_ingredients: p.flagged_ingredients ?? [],
                good_ingredients: p.good_ingredients ?? [],
                url: p.url ?? null,
              })),
            }),
          }
        )

        if (!summaryResponse.ok) {
          throw new Error(`Summary request failed with status ${summaryResponse.status}`)
        }

        const data: SearchSummaryResponse = await summaryResponse.json()
        if (requestId === latestRequestId.current) {
          setSummaryText(data.summary || '')
          setSummarySources(data.sources || [])
        }
      } catch {
        if (requestId === latestRequestId.current) {
          setSummaryText('')
          setSummarySources([])
          setSummaryError('AI summary unavailable for this search.')
        }
      } finally {
        if (requestId === latestRequestId.current) {
          setIsSummaryLoading(false)
        }
      }
    }

    try {
      // Only one phase: useRag controls whether RAG is used in backend
      const response = await fetch(`/api/products/search?${params.toString()}&include_expanded=true`)
      if (!response.ok) throw new Error(`Search failed: ${response.status}`)
      const data: ExpandedSearchResponse | Product[] = await response.json()
      if (requestId !== latestRequestId.current) return
      // If include_expanded, expect ExpandedSearchResponse, else Product[]
      if (Array.isArray(data)) {
        setProducts(data)
        setExpandedQuery('')
        void runSummary(data as Product[])
      } else {
        setProducts(data.results)
        setExpandedQuery(data.rag_query || '')
        void runSummary(data.results)
      }
      setIsSearching(false)
      setIsRefining(false)
    } catch {
      if (requestId === latestRequestId.current) {
        setProducts([])
        setSummaryText('')
        setSummarySources([])
        setSummaryError('')
        setIsSummaryLoading(false)
        setIsSearching(false)
      }
    }
  }

  const executeSearch = (term: string): void => {
    const trimmed = term.trim()
    latestRequestId.current += 1
    setExpandedQuery('')
    setVisibleCount(24)

    if (!trimmed) {
      setSearchTerm('')
      setIsSearching(false)
      setProducts([])
      setSummaryText('')
      setSummarySources([])
      setSummaryError('')
      setIsSummaryLoading(false)
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
      setSummaryText('')
      setSummarySources([])
      setSummaryError('')
      setIsSummaryLoading(false)
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

  // Filter products by included/excluded ingredients
  const filteredProducts = products.filter(product => {
    const ingredients = (product.ingredients || '').toLowerCase();
    // Exclude if any excluded ingredient is present
    if (excludeIngredients.some(ing => ingredients.includes(ing))) return false;
    // If includes are set, only show if all are present
    if (includeIngredients.length > 0 && !includeIngredients.every(ing => ingredients.includes(ing))) return false;
    return true;
  });
  const visibleProducts = filteredProducts.slice(0, visibleCount)
  const canShowMore = products.length > visibleCount
  const skeletonCount = 6
  const exampleQueries = [
    'moisturizer for eczema',
    'toner for dry, sensitive skin',
    'cleanser without niacinamide',
    'i have acne. find me a serum that targets it',
  ]

  const splitIndex = Math.ceil(exampleQueries.length / 2)
  const exampleQueryRows = [
    exampleQueries.slice(0, splitIndex),
    exampleQueries.slice(splitIndex),
  ].filter((row) => row.length > 0)
  const didYouMean = getSuggestedQuery(searchTerm, products)

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
            placeholder="Search for a skincare product (e.g. 'moisturizer for dry skin')"
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

        {/* Example queries: only show if not searched yet */}
        {!hasSearched && (
          <div className="example-query-grid fade-up-anim">
            <p>Try a query:</p>
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
        )}

        {/* RAG toggle and ingredient filter controls */}
        <div className="rag-ingredient-row fade-up-anim" style={{ marginTop: '1rem', marginBottom: '0.5rem', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', width: '100%', gap: '1.5rem' }}>
          <button
            type="button"
            className={`rag-toggle-btn${useRag ? ' active' : ''}`}
            onClick={() => setUseRag(v => !v)}
          >
            RAG {useRag ? '(On)' : '(Off)'}
          </button>
          <div className="ingredient-filter-group">
            <p>Optional:</p>
            <input
              type="text"
              className="ingredient-input"
              placeholder="Input an ingredient to include or exclude (e.g. 'niacinamide')"
              value={ingredientInput}
              onChange={e => setIngredientInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  const val = ingredientInput.trim().toLowerCase();
                  if (!val) return;
                  if (ingredientMode === 'include' && !includeIngredients.includes(val)) {
                    setIncludeIngredients([...includeIngredients, val]);
                  } else if (ingredientMode === 'exclude' && !excludeIngredients.includes(val)) {
                    setExcludeIngredients([...excludeIngredients, val]);
                  }
                  setIngredientInput('');
                }
              }}
            />
            <button
              type="button"
              className={`rag-toggle-btn ${ingredientMode === 'include' ? 'active' : ''}`}
              onClick={() => setIngredientMode('include')}
            >
              Include
            </button>
            <button
              type="button"
              className={`rag-toggle-btn ${ingredientMode === 'exclude' ? 'active' : ''}`}
              onClick={() => setIngredientMode('exclude')}
            >
              Exclude
            </button>
          </div>
          <div className="ingredient-tags">
            {includeIngredients.map((ing, i) => (
              <span key={ing + i} className="ingredient-tag include">+{ing} <button type="button" onClick={() => setIncludeIngredients(includeIngredients.filter(x => x !== ing))}>×</button></span>
            ))}
            {excludeIngredients.map((ing, i) => (
              <span key={ing + i} className="ingredient-tag exclude">-{ing} <button type="button" onClick={() => setExcludeIngredients(excludeIngredients.filter(x => x !== ing))}>×</button></span>
            ))}
          </div>
        </div>
      </div>

      {/* Filters & sort */}
      <div className="filter-bar">
        <p>Filter By:</p>
        <select value={filters.category} onChange={e => handleFilterChange('category', e.target.value)}>
          <option value="">All Categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <input type="number" placeholder="Min $" min={0} value={filters.minPrice} onChange={e => handleFilterChange('minPrice', e.target.value)} />
        <input type="number" placeholder="Max $" min={0} value={filters.maxPrice} onChange={e => handleFilterChange('maxPrice', e.target.value)} />
        <select value={filters.minRating} onChange={e => handleFilterChange('minRating', e.target.value)}>
          <option value="">Any Rating</option>
          <option value="4.5">4.5+ stars</option>
          <option value="4">4+ stars</option>
          <option value="3.5">3.5+ stars</option>
          <option value="3">3+ stars</option>
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
        {searchTerm.trim() && useLlm && (
          useRag ? (
            (isSummaryLoading || summaryText || summaryError) && (
              <section className="ai-summary-panel" aria-live="polite" aria-busy={isSummaryLoading}>
                <span className="ai-summary-header">AI Overview of Top Matches</span>
                {expandedQuery && (
                  <p className="ai-summary-expanded-query">
                    Expanded Query with RAG: <em>"{expandedQuery}"</em>
                  </p>
                )}

                {isSummaryLoading && (
                  <div className="ai-summary-loading" role="status">
                    <span className="ai-summary-shimmer line-1" />
                    <span className="ai-summary-shimmer line-2" />
                  </div>
                )}

                {!isSummaryLoading && summaryText && (
                  <p className="ai-summary-text">{renderWithBold(summaryText)}</p>
                )}

                {!isSummaryLoading && summaryError && (
                  <p className="ai-summary-error">{summaryError}</p>
                )}

                <span className="ai-summary-top-products">Top Recommended Products:</span>

                {!isSummaryLoading && summarySources.length > 0 && (
                  <div className="ai-summary-sources" aria-label="Summary sources">
                    {summarySources.map((source) => (
                      source.url ? (
                        <a key={`${source.id}-${source.name}`} href={source.url} target="_blank" rel="noreferrer" className="ai-summary-source-link">
                          <span className="ai-summary-source-name">{source.name}</span>
                          <span className="ai-summary-source-divider">by</span>
                          <span className="ai-summary-source-brand">{source.brand}</span>
                        </a>
                      ) : (
                        <span key={`${source.id}-${source.name}`} className="ai-summary-source-link muted">
                          <span className="ai-summary-source-name">{source.name}</span>
                          <span className="ai-summary-source-divider">·</span>
                          <span className="ai-summary-source-brand">{source.brand}</span>
                        </span>
                      )
                    ))}
                  </div>
                )}
              </section>
            )
          ) : (
            <section className="ai-summary-panel" aria-live="polite">
              <span className="ai-summary-header">AI Overview of Top Matches</span>
              <p className="ai-summary-error" style={{ marginTop: 12 }}>
                AI overview and expanded user query not available. Please enable RAG search.
              </p>
            </section>
          )
        )}

        {searchTerm.trim() && isSearching && (
          <p className="search-status">Searching...</p>
        )}
        {searchTerm.trim() && !isSearching && products.length > 0 && (
          <p className="result-count">
            {products.length} result{products.length !== 1 ? 's' : ''} for "{expandedQuery}".
            {isRefining && <span className="refining-badge"> Refining with AI…</span>}
            {didYouMean && (
              <>
                {' '}
                <span className="did-you-mean-copy">Did you mean</span>{' '}
                <span className="did-you-mean-copy">"</span>
                <button
                  type="button"
                  className="did-you-mean-button"
                  onClick={() => {
                    setSearchInput(didYouMean)
                    executeSearch(didYouMean)
                  }}
                >
                  {didYouMean}
                </button>
                <span className="did-you-mean-copy">"?</span>

              </>
            )}
          </p>
        )}
        {searchTerm.trim() && !isSearching && products.length === 0 && (
          <div className="empty-state">
            <p>No products found for "{searchTerm}"</p>
            <p className="empty-hint">Try a different search term or adjust your filters.</p>
          </div>
        )}
        {searchTerm.trim() && isSearching && (
          <>
            {/* First row */}
            {Array.from({ length: skeletonCount }).map((_, index) => (
              <div key={`skeleton-${index}`} className="product-item skeleton-card" aria-hidden="true">
                <div className="card-header">
                  <div className="skeleton-line skeleton-line-brand" />
                  <div className="skeleton-line skeleton-line-title" />
                </div>
                <div className="pill-row">
                  <span className="skeleton-pill" />
                  <span className="skeleton-pill" />
                </div>
                <div className="meta-row">
                  <div className="skeleton-line skeleton-line-stars" />
                  <div className="skeleton-line skeleton-line-reviews" />
                  <div className="skeleton-line skeleton-line-price" />
                </div>
                <div className="skeleton-line skeleton-line-body" />
                <div className="skeleton-line skeleton-line-body short" />
                <div className="match-score-wrapper">
                  <div className="skeleton-line skeleton-line-score" />
                </div>
              </div>
            ))}
            {/* Second row */}
            {Array.from({ length: skeletonCount }).map((_, index) => (
              <div key={`skeleton-row2-${index}`} className="product-item skeleton-card" aria-hidden="true">
                <div className="card-header">
                  <div className="skeleton-line skeleton-line-brand" />
                  <div className="skeleton-line skeleton-line-title" />
                </div>
                <div className="pill-row">
                  <span className="skeleton-pill" />
                  <span className="skeleton-pill" />
                </div>
                <div className="meta-row">
                  <div className="skeleton-line skeleton-line-stars" />
                  <div className="skeleton-line skeleton-line-reviews" />
                  <div className="skeleton-line skeleton-line-price" />
                </div>
                <div className="skeleton-line skeleton-line-body" />
                <div className="skeleton-line skeleton-line-body short" />
                <div className="match-score-wrapper">
                  <div className="skeleton-line skeleton-line-score" />
                </div>
              </div>
            ))}
          </>
        )}
        {!isSearching && visibleProducts.map((product, index) => (
          <div
            key={index}
            className={`product-item${product.out_of_stock ? ' out-of-stock' : ''}`}
            style={{ cursor: 'pointer' }}
            onClick={() => {
              // Find 3 most similar products by SVD dimensions (cosine similarity)
              if (product.top_dimensions && products.length > 1) {
                // Use top SVD dimensions as a vector
                const dims = product.top_dimensions.top.map(d => d.contribution);
                // Compute similarity for all other products with SVD info
                const sims = products
                  .filter(p => p.id !== product.id && p.top_dimensions)
                  .map(p => {
                    const otherDims = p.top_dimensions!.top.map(d => d.contribution);
                    // Pad to same length
                    const len = Math.min(dims.length, otherDims.length);
                    const a = dims.slice(0, len);
                    const b = otherDims.slice(0, len);
                    // Cosine similarity
                    const dot = a.reduce((sum, v, i) => sum + v * b[i], 0);
                    const normA = Math.sqrt(a.reduce((sum, v) => sum + v * v, 0));
                    const normB = Math.sqrt(b.reduce((sum, v) => sum + v * v, 0));
                    const sim = normA && normB ? dot / (normA * normB) : 0;
                    return { id: p.id, name: p.name, brand: p.brand, score: sim };
                  });
                sims.sort((a, b) => b.score - a.score);
              } else {
              }
            }}
          >

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
              <span className="badge badge-category">{normalizeCategory(product.category)}</span>

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

                    {/* <p className="svd-section-label">▼ Bottom 5 Dimensions</p>
                  {product.top_dimensions.bottom.map((d, i) => (
                    <div key={i} className="svd-dim-row">
                      <span className="svd-neg">Dim {d.dim}</span>
                      <span className="svd-dim-contrib svd-neg">{d.contribution.toFixed(4)}</span>
                      <span className="svd-dim-terms">{d.top_terms.join(', ')}</span>
                    </div>
                  ))} */}
                  </div>
                )}
              </details>
            )}

            {product.top_dimensions && (
              <details className="description-dropdown">
                <summary>Similar Products</summary>
                {(() => {
                  const similar = getSimilarProducts(product, products);
                  return similar.length === 0 ? (
                    <p className="product-description" style={{ marginTop: '0.4rem', color: '#9EAF9E' }}>
                      No similar products found.
                    </p>
                  ) : (
                    <ul style={{ margin: '0.4rem 0 0 0', padding: '0 0 0 1.1em' }}>
                      {similar.map(sp => (
                        <li key={sp.id} style={{ marginBottom: '0.3em', fontSize: '0.88rem', color: '#4A5A4A' }}>
                          <span style={{ fontWeight: 600, color: '#3A6B4A' }}>{sp.name}</span>
                          {' '}by {sp.brand}
                          <span style={{ color: '#9EAF9E', marginLeft: '6px' }}>
                            {(sp.score * 100).toFixed(1)}% match
                          </span>
                        </li>
                      ))}
                    </ul>
                  );
                })()}
              </details>
            )}

            <div className="match-score-wrapper">
              <p className="match-score-label">Match Score: {product.score.toFixed(1)}%</p>
            </div>
          </div>
        ))}

        {/* Show more button */}
        {searchTerm.trim() && !isSearching && canShowMore && (
          <button
            type="button"
            className="show-more-button"
            onClick={() => setVisibleCount((current) => current + 60)}
          >
            Show {Math.min(60, products.length - visibleCount)} more products
          </button>
        )}
      </div>

      {/* Chat (only when USE_LLM = True in routes.py) */}
      {useLlm && <Chat onSearchTerm={handleChatSearch} currentSearchTerm={searchTerm} minimized />}
    </div>
  )
}

export default App