export interface Product {
  id: number;
  name: string;
  brand: string;
  price: number;
  sale_price: number | null;
  rating: number;
  review_count: number;
  loves_count: number;
  category: string;
  ingredients: string;
  description: string;
  highlights: string | null;
  is_new: boolean;
  sephora_exclusive: boolean;
  limited_edition: boolean;
  out_of_stock: boolean;
  score: number;
  safety_score: number;
  flagged_ingredients: string[];
  avoided_ingredients?: string[];
  good_ingredients: string[];
  url: string | null;
  svd_score?: number;
top_dimensions?: { dim: number; contribution: number; top_terms: string[] }[];
}
