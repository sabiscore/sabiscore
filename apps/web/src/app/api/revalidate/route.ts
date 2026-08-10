import { revalidatePath } from 'next/cache';
import { NextRequest, NextResponse } from 'next/server';

/**
 * Next.js ISR Revalidation API
 * 
 * Allows backend to trigger on-demand revalidation when match data updates.
 * Called by WebSocket layer when goals/odds change requiring fresh renders.
 * 
 * Usage: POST /api/revalidate with { secret, path }
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { secret, path } = body;

    // Revalidation is disabled until both services receive the same secret.
    const revalidateSecret = process.env.REVALIDATE_SECRET;
    if (!revalidateSecret) {
      return NextResponse.json(
        { error: 'Revalidation is not configured' },
        { status: 503 },
      );
    }
    
    if (secret !== revalidateSecret) {
      return NextResponse.json(
        { error: 'Invalid secret' },
        { status: 401 }
      );
    }

    // Validate path format
    if (!path || typeof path !== 'string') {
      return NextResponse.json(
        { error: 'Invalid path parameter' },
        { status: 400 }
      );
    }

    // Revalidate the specified path
    revalidatePath(path);

    return NextResponse.json(
      { 
        revalidated: true, 
        path,
        timestamp: new Date().toISOString() 
      },
      { status: 200 }
    );

  } catch {
    console.error('Revalidation error');
    
    return NextResponse.json(
      { 
        error: 'Revalidation failed',
      },
      { status: 500 }
    );
  }
}

// Health check endpoint
export async function GET() {
  return NextResponse.json(
    { 
      status: 'ready',
      endpoint: '/api/revalidate',
      method: 'POST'
    },
    { status: 200 }
  );
}
