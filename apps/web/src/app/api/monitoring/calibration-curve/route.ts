/**
 * Calibration Curve API
 * 
 * Returns calibration curve data for visualization.
 */

import { NextResponse } from 'next/server';
import { kv } from '@vercel/kv';

export const runtime = 'nodejs';

export async function GET() {
  try {
    // Generate calibration curve from binned predictions
    const bins = 10;
    const curve: { predicted: number; actual: number }[] = [];
    
    for (let i = 0; i < bins; i++) {
      const minProb = i * 10;
      const maxProb = (i + 1) * 10;
      const key = `calibration:bin:${minProb}-${maxProb}`;
      
      const data = await kv.get<string>(key);
      
      if (data) {
        const parsed = JSON.parse(data);
        const actual = parsed.total > 0 ? parsed.correct / parsed.total : 0;
        const predicted = (minProb + maxProb) / 2 / 100;
        
        curve.push({ predicted, actual });
      }
    }
    
    return NextResponse.json({
      curve,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('Calibration curve API error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch calibration curve' },
      { status: 500 }
    );
  }
}
