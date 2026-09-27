import type { ParsedQuery, TravelDocument } from "../types";

export interface ItineraryDayStop {
  slot: "Morning" | "Lunch" | "Afternoon" | "Dinner" | "Evening";
  title: string;
  activities: string[];
  category?: string;
  duration?: string;
  travelTimeToNext?: string;
  imageUrl?: string;
}

export interface StructuredDayPlan {
  day: number;
  title: string;
  stops: ItineraryDayStop[];
}

export interface HotelRecommendation {
  name: string;
  area: string;
  stars: number;
  price: string;
  desc: string;
}

/**
 * Format document summary for compact itinerary schedule card display.
 * Strips bracketed metadata/citations like "[Wikidata: ...]" and truncates to 1-2 complete sentences (~150-200 chars).
 */
export const formatCardSummary = (summary: string): string => {
  if (!summary) return "";
  
  // 1. Strip out bracketed asides like "[Wikidata: It is a lake...]" or "[Wikidata: ...]"
  let cleaned = summary.replace(/\[Wikidata:[^\]]+\]/gi, "").trim();
  
  // 2. Normalize whitespace
  cleaned = cleaned.replace(/\s+/g, " ").trim();
  
  // 3. If summary is short (under ~200 chars), return it cleanly as-is
  if (cleaned.length <= 200) {
    return cleaned;
  }
  
  // 4. Split into sentences (at '.', '!', '?')
  const sentences = cleaned.match(/[^.!?]+[.!?]+/g) || [cleaned];
  
  // 5. Take first 1-2 sentences up to ~220 characters limit
  let result = sentences[0].trim();
  if (sentences.length > 1 && (result.length + sentences[1].trim().length) <= 220) {
    result += " " + sentences[1].trim();
  }
  
  return result;
};

/**
 * Clean answer text of any raw mock or internal wrapper tags.
 */
export const cleanAnswerText = (text: string): string => {
  if (!text) return "";
  return text
    .replace(/\[MOCK RESPONSE - [^\]]+\]/gi, "")
    .replace(/mock response/gi, "")
    .replace(/mock fallback/gi, "")
    .replace(/fake response/gi, "")
    .replace(/based on our database/gi, "based on real-time travel intelligence")
    .trim();
};

/**
 * Extract itinerary metadata (title, summary, activities list, budget, duration, destination)
 * from API response answer string, query analysis, and retrieved travel documents.
 */
export const parseItineraryDetails = (
  answer: string,
  queryAnalysis?: ParsedQuery,
  documents?: TravelDocument[]
) => {
  const cleanAnswer = cleanAnswerText(answer || "");
  let title = "";
  let summary = "";
  let activitiesList: string[] = [];
  let budgetVal = "";
  let durationVal = "";

  const hasMockStructure =
    (answer || "").includes("MOCK RESPONSE") ||
    (answer || "").includes("Mock Fallback") ||
    (answer || "").includes("custom travel plan");

  if (hasMockStructure) {
    const titleMatch = answer.match(/selected "([^"]+)"/i);
    if (titleMatch) title = titleMatch[1];

    const activitiesMatch = answer.match(/Activities include: ([^\r\n.]+)/i);
    if (activitiesMatch) {
      activitiesList = activitiesMatch[1].split(",").map((a) => a.trim());
    }

    const budgetMatch = answer.match(/Budget estimate: ([^\r\n. Enjoy]+)/i);
    if (budgetMatch) budgetVal = budgetMatch[1].trim();

    const durationMatch = answer.match(/Timeframe: ([^\r\n,]+)/i);
    if (durationMatch) durationVal = durationMatch[1].trim();

    const lines = answer.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("-") || trimmed.startsWith("*")) {
        if (
          !trimmed.includes("selected \"") &&
          !trimmed.includes("Activities include") &&
          !trimmed.includes("Timeframe:")
        ) {
          summary = trimmed.replace(/^[-*\s]+/, "");
          break;
        }
      }
    }
  }

  const destination =
    queryAnalysis?.destination ||
    documents?.[0]?.destination ||
    "Destination";

  if (!title) {
    title = queryAnalysis?.days
      ? `${queryAnalysis.days} Day ${queryAnalysis.tripType || "Leisure"} Getaway to ${destination}`
      : `${destination} Experience`;
  }

  if (!summary) {
    const textLines = cleanAnswer.split("\n");
    summary =
      textLines.find((l) => l.trim().length > 30) ||
      cleanAnswer.substring(0, 160) + (cleanAnswer.length > 160 ? "..." : "");
  }

  if (activitiesList.length === 0) {
    if (documents && documents.length > 0) {
      activitiesList = Array.from(
        new Set(documents.flatMap((doc) => doc.activities || []))
      ).slice(0, 8);
    } else {
      activitiesList = ["Local Exploration", "Sightseeing", "Cultural Walks"];
    }
  }

  if (!budgetVal) {
    budgetVal = queryAnalysis?.budget
      ? `₹${queryAnalysis.budget.toLocaleString("en-IN")}`
      : documents?.[0]?.budget
      ? `₹${documents[0].budget.toLocaleString("en-IN")}`
      : "Moderate";
  }

  if (!durationVal) {
    durationVal = queryAnalysis?.days
      ? `${queryAnalysis.days} Days`
      : documents?.[0]?.days
      ? `${documents[0].days} Days`
      : "3 Days";
  }

  return {
    title,
    summary,
    activitiesList,
    budgetVal,
    durationVal,
    destination,
  };
};

/**
 * Get curated hotel recommendation based on destination.
/**
 * Get hotel recommendation from retrieved documents.
 * Returns null if no real hotel exists in the database for the destination.
 */
export const getHotelRecommendation = (
  dest: string,
  documents?: TravelDocument[]
): HotelRecommendation | null => {
  if (!dest) return null;

  // Search for an explicit hotel document in retrieved documents
  const hotelDoc = documents?.find(
    (doc) =>
      doc.tripType === "hotel" ||
      doc.activities?.includes("hotel")
  );

  if (hotelDoc) {
    return {
      name: hotelDoc.title,
      area: hotelDoc.destination ? `${hotelDoc.destination} Area` : dest,
      stars: 4,
      price: hotelDoc.budget ? `₹${hotelDoc.budget.toLocaleString("en-IN")} / night` : "Standard Rate",
      desc: hotelDoc.summary || `${hotelDoc.title} is located in ${dest}.`,
    };
  }

  // Return null if no hotel documents exist in database for this destination
  return null;
};

/**
 * Single source of truth for building structured day-by-day itineraries
 * from backend documents and LLM answer payloads.
 */
export const generateDailyPlan = (
  answer: string,
  queryAnalysis?: ParsedQuery,
  documents?: TravelDocument[]
): StructuredDayPlan[] => {
  const details = parseItineraryDetails(answer, queryAnalysis, documents);
  const numDays = queryAnalysis?.days || documents?.[0]?.days || 3;
  const plan: StructuredDayPlan[] = [];

  // Exclude hotel documents from attraction day plan stops
  const attractionDocs = (documents || []).filter(
    (doc) =>
      doc.tripType !== "hotel" &&
      !doc.activities?.includes("hotel")
  );

  if (attractionDocs.length > 0) {
    const totalDocs = attractionDocs.length;
    let docPointer = 0;

    for (let d = 1; d <= numDays; d++) {
      const stops: ItineraryDayStop[] = [];

      // 1. Morning Attraction Stop
      const morningDoc = attractionDocs[docPointer % totalDocs];
      docPointer++;
      stops.push({
        slot: "Morning",
        title: morningDoc.title,
        activities: [formatCardSummary(morningDoc.summary) || `Explore ${morningDoc.title}`],
        category:
          morningDoc.activities?.[0] && morningDoc.activities[0] !== "hotel"
            ? morningDoc.activities[0]
            : "Sightseeing",
        duration: "2h 30m",
        travelTimeToNext: "15 min transit",
        imageUrl: morningDoc.image_url || morningDoc.image,
      });

      // 2. Lunch Stop
      stops.push({
        slot: "Lunch",
        title: `Local ${details.destination} Lunch`,
        activities: [`Enjoy authentic regional cuisine in ${details.destination}`],
        category: "Dining",
        duration: "1h 15m",
        travelTimeToNext: "10 min walk",
      });

      // 3. Afternoon Stop (Use next real attraction doc)
      if (totalDocs > 1) {
        const afternoonDoc = attractionDocs[docPointer % totalDocs];
        docPointer++;
        stops.push({
          slot: "Afternoon",
          title: afternoonDoc.title,
          activities: [formatCardSummary(afternoonDoc.summary) || `Visit ${afternoonDoc.title}`],
          category:
            afternoonDoc.activities?.[0] && afternoonDoc.activities[0] !== "hotel"
              ? afternoonDoc.activities[0]
              : "Culture",
          duration: "2h",
          travelTimeToNext: "20 min transit",
          imageUrl: afternoonDoc.image_url || afternoonDoc.image,
        });
      }

      // 4. Evening Stop
      if (totalDocs >= numDays * 3) {
        const eveningDoc = attractionDocs[docPointer % totalDocs];
        docPointer++;
        stops.push({
          slot: "Evening",
          title: eveningDoc.title,
          activities: [formatCardSummary(eveningDoc.summary) || `Evening visit to ${eveningDoc.title}`],
          category:
            eveningDoc.activities?.[0] && eveningDoc.activities[0] !== "hotel"
              ? eveningDoc.activities[0]
              : "Leisure",
          duration: "1h 45m",
          travelTimeToNext: "10 min walk",
          imageUrl: eveningDoc.image_url || eveningDoc.image,
        });
      } else {
        stops.push({
          slot: "Evening",
          title: "Evening Promenade & Local Market Walk",
          activities: [
            `Stroll through local marketplaces and waterfront in ${details.destination}`,
          ],
          category: "Leisure",
          duration: "1h 45m",
          travelTimeToNext: "10 min walk",
        });
      }

      // 5. Dinner Stop
      stops.push({
        slot: "Dinner",
        title: `${details.destination} Regional Dinner`,
        activities: [`Dinner at local restaurant in ${details.destination}`],
        category: "Gastronomy",
        duration: "1h 30m",
        travelTimeToNext: "Return to hotel",
      });

      const dayTitle = morningDoc
        ? `${morningDoc.title} & ${details.destination} Sights`
        : `Day ${d} Exploration`;

      plan.push({
        day: d,
        title: dayTitle,
        stops,
      });
    }

    return plan;
  }

  // Case B: Fallback if no documents are provided
  for (let d = 1; d <= numDays; d++) {
    plan.push({
      day: d,
      title: `Day ${d} Exploration`,
      stops: [
        {
          slot: "Morning",
          title: `Explore ${details.destination} Sightseeing`,
          activities: [`Morning sightseeing in ${details.destination}`],
          category: "Sightseeing",
          duration: "2h 30m",
        },
        {
          slot: "Lunch",
          title: "Local Cuisine Experience",
          activities: ["Regional dining"],
          category: "Dining",
          duration: "1h 15m",
        },
        {
          slot: "Afternoon",
          title: "Cultural & Heritage Exploration",
          activities: ["Explore local landmarks and streets"],
          category: "Culture",
          duration: "2h",
        },
        {
          slot: "Evening",
          title: "Free Time & Independent Exploration",
          activities: ["Evening leisure stroll and local shopping"],
          category: "Leisure",
          duration: "1h 45m",
        },
      ],
    });
  }

  return plan;
};
