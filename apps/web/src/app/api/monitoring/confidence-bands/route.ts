/**
 * Confidence Bands API
 * 
 * Returns accuracy metrics stratified by confidence levels.
 */

import { NextResponse } from 'next/server';
import { kv } from '@vercel/kv';

export const runtime = 'nodejs';

interface ConfidenceBandData {
  band: string;
  minConfidence: number;
  maxConfidence: number;
  correct: number;
  total: number;
  accuracy: number;
  expectedAccuracy: number;
  calibrationError: number;
}

const CONFIDENCE_BANDS = [
  { name: 'Very High', min: 85, max: 100 },
  { name: 'High', min: 75, max: 85 },
  { name: 'Medium-High', min: 65, max: 75 },
  { name: 'Medium', min: 55, max: 65 },
  { name: 'Low', min: 0, max: 55 },
];

export async function GET() {
  try {
    // Fetch confidence tracking data
    const bands: ConfidenceBandData[] = [];
    
    for (const band of CONFIDENCE_BANDS) {
      const key = `confidence:band:${band.min}-${band.max}`;
      const data = await kv.get<string>(key);
      
      if (data) {
        const parsed = JSON.parse(data);
        const accuracy = parsed.total > 0 ? parsed.correct / parsed.total : 0;
        const expectedAccuracy = parsed.total > 0
          ? parsed.totalConfidence / parsed.total / 100
          : (band.min + band.max) / 2 / 100;
        
        bands.push({
          band: band.name,
          minConfidence: band.min,
          maxConfidence: band.max,
          correct: parsed.correct || 0,
          total: parsed.total || 0,
          accuracy,
          expectedAccuracy,
          calibrationError: accuracy - expectedAccuracy,
        });
      } else {
        // No data for this band yet
        bands.push({
          band: band.name,
          minConfidence: band.min,
          maxConfidence: band.max,
          correct: 0,
          total: 0,
          accuracy: 0,
          expectedAccuracy: (band.min + band.max) / 2 / 100,
          calibrationError: 0,
        });
      }
    }
    
    return NextResponse.json({
      bands,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('Confidence bands API error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch confidence bands' },
      { status: 500 }
    );
  }
}
