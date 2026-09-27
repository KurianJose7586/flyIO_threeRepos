export interface ParsedQuery {
  destination: string | null;
  days: number | null;
  budget: number | null;
  travelers: number | null;
  tripType: string | null;
  missing?: string[];
  confidence: number;
  country?: string | null;
  isInternational?: boolean;
}

export interface TravelDocument {
  id: number;
  destination: string;
  title: string;
  summary: string;
  activities: string[];
  days: number;
  budget: number;
  tripType: string;
  keywords: string[];
  score?: number;
  image_url?: string;
  image?: string;
}

export interface ChatSuccessResponse {
  success: true;
  queryAnalysis: ParsedQuery;
  validation: { valid: true; missing: string[] };
  searchMode: "SQL" | "VECTOR";
  searchReason: string;
  metadata: {
    processingTime: string;
    searchMode: "SQL" | "VECTOR";
    documentsRetrieved: number;
    hybridMode: boolean;
    llm: string;
    timestamp: string;
    llmFallbackReason?: string;
    orchestration?: {
      category: "simple" | "long" | "complex";
      reason: string;
      selectedModel: string;
      fallbackChain: string[];
      modelsTried: string[];
    };
    country?: string;
    isInternational?: boolean;
    howToReach?: HowToReach[];
    weatherSummary?: WeatherSummary;
  };
  documents: TravelDocument[];
  pipeline: string[];
  prompt: string;
  answer: string;
  isMock?: boolean;
  howToReach?: HowToReach[];
  weatherSummary?: WeatherSummary;
}

export interface ChatFollowUpResponse {
  success: false;
  needsFollowUp: true;
  question: string;
  queryAnalysis: ParsedQuery;
  pipeline?: string[];
}

export interface ChatErrorResponse {
  success: false;
  error: string;
  detail: string;
  pipeline?: string[];
}

export type ChatResponse = ChatSuccessResponse | ChatFollowUpResponse | ChatErrorResponse;

export interface HealthResponse {
  status: string;
  version: string;
  hybridMode: boolean;
  llm: string;
  documents: number;
  uptime: string;
  qdrantReady?: boolean;
  qdrantCount?: number;
  crawlerStatus?: string;
  crawlerDocumentsCount?: number;
  lastImportTime?: string;
}

export interface DebugConfigResponse {
  hybridMode: boolean;
  llmConfigured: boolean;
  mockMode: boolean;
}

export interface Restaurant {
  id: number;
  name: string;
  area: string;
  cuisine: string;
  price_range: string;
  price_inr?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  description: string;
}

export interface HowToReach {
  id: number;
  mode: string;
  details: string;
}

export interface WeatherMonth {
  id: number;
  month: number;
  temp_min_c: number;
  temp_max_c: number;
  aqi: number;
  aqi_category: string;
}

export interface ItineraryAttraction {
  id: number;
  title: string;
  destination: string;
  category: string;
  avg_visit_duration_hrs: number;
  latitude?: number;
  longitude?: number;
  summary: string;
}

export interface ItineraryDay {
  day: number;
  attractions: ItineraryAttraction[];
  restaurant_suggestions: Restaurant[];
}

export interface WeatherSummary {
  avg_temp_min_c: number;
  avg_temp_max_c: number;
  avg_aqi: number;
  overall_aqi_category: string;
  total_months_recorded: number;
}

export interface DestinationItineraryResponse {
  success: boolean;
  destination: string;
  destination_id: number;
  duration_days: number;
  how_to_reach: HowToReach[];
  weather_summary: WeatherSummary;
  days: ItineraryDay[];
}


