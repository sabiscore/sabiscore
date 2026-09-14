import '@/lib/patch-path-url-join';
import { ImageResponse } from 'next/og';

export const runtime = 'nodejs';
export const size = { width: 192, height: 192 };
export const contentType = 'image/png';

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '100%',
          height: '100%',
          background: 'radial-gradient(circle at 0% 0%, #0A1F15 0%, #030A07 52%, #010302 100%)',
          borderRadius: 40,
          boxShadow: 'inset 0 0 0 2px rgba(26,77,51,0.72), inset 0 0 0 3px rgba(15,89,56,0.18)',
        }}
      >
        <svg viewBox="0 0 48 48" width="138" height="138" fill="none">
          <path
            d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
            stroke="#06140D"
            strokeWidth="7.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity="0.42"
          />
          <path
            d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
            stroke="#2BDC97"
            strokeWidth="4.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
            stroke="#FFFFFF"
            strokeWidth="1.05"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity="0.24"
          />
          <circle cx="10.5" cy="13.5" r="2.35" fill="#2BDC97" opacity="0.62" />
          <circle cx="38.4" cy="38.5" r="3.65" fill="#C4FF4D" />
          <circle cx="38.4" cy="38.5" r="1.35" fill="#FFFFFF" opacity="0.92" />
        </svg>
      </div>
    ),
    { ...size },
  );
}
