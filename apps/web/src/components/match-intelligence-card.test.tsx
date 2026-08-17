import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  MatchIntelligenceCard,
  type MatchIntelligenceFixture,
} from './match-intelligence-card';

function fixture(overrides: Partial<MatchIntelligenceFixture> = {}): MatchIntelligenceFixture {
  return {
    matchId: 'fix-1',
    homeTeam: 'Arsenal',
    awayTeam: 'Chelsea',
    kickoffUtc: '2026-08-15T15:00:00Z',
    league: 'EPL',
    predictionAvailable: true,
    prediction: {
      home_win: 0.5,
      draw: 0.25,
      away_win: 0.25,
      confidence: 0.7,
      model_version: 'v6_phase8',
    },
    edge_pct: 5.0,
    ...overrides,
  };
}

describe('MatchIntelligenceCard', () => {
  it('renders the home and away team names from props', () => {
    render(<MatchIntelligenceCard fixture={fixture()} />);
    expect(screen.getByTestId('home-team')).toHaveTextContent('Arsenal');
    expect(screen.getByTestId('away-team')).toHaveTextContent('Chelsea');
  });

  it('renders match probabilities and model provenance', () => {
    render(<MatchIntelligenceCard fixture={fixture()} />);
    expect(screen.getByLabelText('Match outcome probabilities')).toBeInTheDocument();
    expect(screen.getByText('Model v6_phase8')).toBeInTheDocument();
  });

  it('never infers a value-bet claim from edge_pct alone', () => {
    render(<MatchIntelligenceCard fixture={fixture({ edge_pct: 99 })} />);
    expect(screen.queryByText(/value bet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/edge/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Match outcome probabilities')).toBeInTheDocument();
  });

  it('renders the unavailable reason instead of probability bars when prediction is unavailable', () => {
    render(
      <MatchIntelligenceCard
        fixture={fixture({ predictionAvailable: false, prediction: null, unavailableReason: 'Lineups pending' })}
      />
    );
    expect(screen.getByText('Lineups pending')).toBeInTheDocument();
    expect(screen.queryByLabelText('Match outcome probabilities')).not.toBeInTheDocument();
  });

  it('falls back to the default unavailable message when no reason is given', () => {
    render(
      <MatchIntelligenceCard fixture={fixture({ predictionAvailable: false, prediction: null })} />
    );
    expect(screen.getByText('Prediction not yet available')).toBeInTheDocument();
  });
});
