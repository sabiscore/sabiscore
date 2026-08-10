"""
Twitter (X) sentiment analyzer for real-time market sentiment and narrative tracking.
Integrates with prediction pipeline to detect market overreactions.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SentimentScore:
    """Sentiment analysis result"""
    score: float  # -1.0 to 1.0
    magnitude: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    sample_size: int
    trending: bool


class TwitterSentimentAnalyzer:
    """
    Real-time sentiment analysis from Twitter/X for:
    - Team momentum narratives
    - Player injury impact perception  
    - Market overreaction detection
    - Referee bias sentiment
    - Weather/travel concerns
    
    Creative Integration:
    - Correlate sentiment spikes with odds movements
    - Detect narrative-driven market inefficiencies
    - Weight sentiment by follower count and credibility
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        api_key: Optional[str] = None,
    ):
        self.redis = redis_client
        self.api_key = api_key
        self.cache_ttl = 300  # 5 minutes cache
        
        # Sentiment keywords with weights
        self.positive_keywords = {
            'win', 'wins', 'winning', 'dominate', 'dominated', 'crushing',
            'excellent', 'brilliant', 'unstoppable', 'momentum', 'form',
            'confident', 'strong', 'clinical', 'sharp', 'fit', 'ready',
        }
        
        self.negative_keywords = {
            'lose', 'losing', 'lost', 'terrible', 'awful', 'poor', 'weak',
            'injury', 'injured', 'injured', 'fatigue', 'tired', 'exhausted',
            'crisis', 'disaster', 'shambles', 'collapse', 'struggling',
        }
        
        # Credible sources (verified accounts, analysts, journalists)
        self.credible_sources = {
            'OptaJoe', 'FBref', 'Statsbomb', 'SkySportsStatto',
            'WhoScored', 'xGPhilosophy', 'Caley_graphics',
        }

    async def analyze_match_sentiment(
        self,
        home_team: str,
        away_team: str,
        hours_before_kickoff: int = 24,
    ) -> Dict[str, Any]:
        """
        Analyze Twitter sentiment for upcoming match.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            hours_before_kickoff: Hours before match to analyze
            
        Returns:
            Dict with sentiment scores and insights:
            {
                'home_sentiment': SentimentScore,
                'away_sentiment': SentimentScore,
                'narrative_bias': float,  # -1.0 to 1.0
                'market_overreaction': bool,
                'key_topics': List[str],
                'credibility_weighted_score': float,
            }
        """
        try:
            # Check cache
            cache_key = f"sentiment:{home_team}:{away_team}"
            if self.redis:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info(f"Sentiment cache HIT for {home_team} vs {away_team}")
                    import json
                    return json.loads(cached)
            
            # Fetch tweets (in production, use Twitter API v2)
            home_tweets = await self._fetch_tweets(home_team, hours_before_kickoff)
            away_tweets = await self._fetch_tweets(away_team, hours_before_kickoff)
            
            # Analyze sentiment
            home_sentiment = self._analyze_tweets(home_tweets)
            away_sentiment = self._analyze_tweets(away_tweets)
            
            # Calculate narrative bias
            narrative_bias = home_sentiment.score - away_sentiment.score
            
            # Detect market overreaction
            # If sentiment is extreme (>0.6 or <-0.6) and trending, likely overreaction
            market_overreaction = (
                (abs(narrative_bias) > 0.6) and
                (home_sentiment.trending or away_sentiment.trending)
            )
            
            # Extract key topics
            key_topics = self._extract_key_topics(home_tweets + away_tweets)
            
            # Calculate credibility-weighted score
            credibility_score = self._calculate_credibility_weighted_score(
                home_tweets + away_tweets
            )
            
            result = {
                'home_team': home_team,
                'away_team': away_team,
                'home_sentiment': {
                    'score': home_sentiment.score,
                    'magnitude': home_sentiment.magnitude,
                    'confidence': home_sentiment.confidence,
                    'sample_size': home_sentiment.sample_size,
                    'trending': home_sentiment.trending,
                },
                'away_sentiment': {
                    'score': away_sentiment.score,
                    'magnitude': away_sentiment.magnitude,
                    'confidence': away_sentiment.confidence,
                    'sample_size': away_sentiment.sample_size,
                    'trending': away_sentiment.trending,
                },
                'narrative_bias': round(narrative_bias, 3),
                'market_overreaction': market_overreaction,
                'key_topics': key_topics,
                'credibility_weighted_score': round(credibility_score, 3),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            
            # Cache result
            if self.redis:
                import json
                await self.redis.setex(cache_key, self.cache_ttl, json.dumps(result))
            
            return result
            
        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            raise

    async def _fetch_tweets(
        self,
        team: str,
        hours: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch tweets mentioning team.
        
        In production, use Twitter API v2:
        ```python
        import tweepy
        
        client = tweepy.Client(bearer_token=self.api_key)
        
        query = f"{team} (betting OR odds OR prediction OR tip) -is:retweet"
        tweets = client.search_recent_tweets(
            query=query,
            max_results=100,
            start_time=datetime.now(timezone.utc) - timedelta(hours=hours),
            tweet_fields=['created_at', 'author_id', 'public_metrics'],
        )
        
        return [
            {
                'text': tweet.text,
                'created_at': tweet.created_at,
                'author_id': tweet.author_id,
                'metrics': tweet.public_metrics,
            }
            for tweet in tweets.data
        ]
        ```
        """
        # Placeholder - return empty list
        return []

    def _analyze_tweets(self, tweets: List[Dict[str, Any]]) -> SentimentScore:
        """
        Analyze sentiment from tweets using keyword matching and NLP.
        
        In production, use transformer model:
        ```python
        from transformers import pipeline
        
        sentiment_model = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english"
        )
        
        scores = [
            sentiment_model(tweet['text'])[0]['score']
            for tweet in tweets
        ]
        ```
        """
        if not tweets:
            return SentimentScore(
                score=0.0,
                magnitude=0.0,
                confidence=0.0,
                sample_size=0,
                trending=False,
            )
        
        # Simple keyword-based sentiment
        scores = []
        for tweet in tweets:
            text = tweet.get('text', '').lower()
            
            pos_count = sum(1 for word in self.positive_keywords if word in text)
            neg_count = sum(1 for word in self.negative_keywords if word in text)
            
            if pos_count + neg_count > 0:
                score = (pos_count - neg_count) / (pos_count + neg_count)
                scores.append(score)
        
        if not scores:
            return SentimentScore(
                score=0.0,
                magnitude=0.0,
                confidence=0.0,
                sample_size=len(tweets),
                trending=False,
            )
        
        avg_score = sum(scores) / len(scores)
        magnitude = abs(avg_score)
        confidence = min(1.0, len(scores) / 100)  # More tweets = higher confidence
        
        # Detect trending (rapid increase in tweet volume)
        # In production, compare to historical baseline
        trending = len(tweets) > 50  # Simple threshold
        
        return SentimentScore(
            score=avg_score,
            magnitude=magnitude,
            confidence=confidence,
            sample_size=len(tweets),
            trending=trending,
        )

    def _extract_key_topics(self, tweets: List[Dict[str, Any]]) -> List[str]:
        """Extract key topics from tweets using frequency analysis"""
        if not tweets:
            return []
        
        # Common topics in sports betting
        topics = {
            'injury', 'injuries', 'form', 'momentum', 'tactics', 'referee',
            'weather', 'travel', 'fatigue', 'motivation', 'pressure',
            'lineup', 'rotation', 'squad depth', 'home advantage',
        }
        
        # Count topic mentions
        topic_counts = {topic: 0 for topic in topics}
        for tweet in tweets:
            text = tweet.get('text', '').lower()
            for topic in topics:
                if topic in text:
                    topic_counts[topic] += 1
        
        # Return top 3 topics
        top_topics = sorted(
            topic_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]
        
        return [topic for topic, count in top_topics if count > 0]

    def _calculate_credibility_weighted_score(
        self,
        tweets: List[Dict[str, Any]]
    ) -> float:
        """
        Calculate sentiment score weighted by source credibility.
        Verified accounts and known analysts get higher weight.
        """
        if not tweets:
            return 0.0
        
        weighted_scores = []
        total_weight = 0.0
        
        for tweet in tweets:
            # Get author info
            author = tweet.get('author_id', '')
            metrics = tweet.get('metrics', {})
            followers = metrics.get('followers_count', 0)
            
            # Calculate weight (credible sources + follower count)
            weight = 1.0
            if author in self.credible_sources:
                weight = 5.0  # 5x weight for credible sources
            elif followers > 10000:
                weight = 2.0  # 2x weight for influencers
            
            # Get sentiment score
            text = tweet.get('text', '').lower()
            pos_count = sum(1 for word in self.positive_keywords if word in text)
            neg_count = sum(1 for word in self.negative_keywords if word in text)
            
            if pos_count + neg_count > 0:
                score = (pos_count - neg_count) / (pos_count + neg_count)
                weighted_scores.append(score * weight)
                total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return sum(weighted_scores) / total_weight

    async def detect_narrative_shifts(
        self,
        team: str,
        lookback_hours: int = 48,
    ) -> Dict[str, Any]:
        """
        Detect narrative shifts (sudden changes in sentiment).
        Useful for identifying market inefficiencies.
        
        Returns:
            Dict with shift detection results:
            {
                'shift_detected': bool,
                'shift_magnitude': float,
                'shift_direction': str,  # 'positive' or 'negative'
                'shift_velocity': float,  # Rate of change
                'potential_value': float,  # Betting opportunity score
            }
        """
        try:
            # Fetch tweets in time windows
            recent_tweets = await self._fetch_tweets(team, hours=6)
            historical_tweets = await self._fetch_tweets(team, hours=lookback_hours)
            
            # Analyze both windows
            recent_sentiment = self._analyze_tweets(recent_tweets)
            historical_sentiment = self._analyze_tweets(
                historical_tweets[len(recent_tweets):]  # Exclude recent
            )
            
            # Calculate shift
            shift_magnitude = abs(recent_sentiment.score - historical_sentiment.score)
            shift_detected = shift_magnitude > 0.3  # Threshold for significant shift
            
            shift_direction = (
                'positive' if recent_sentiment.score > historical_sentiment.score
                else 'negative'
            )
            
            # Calculate velocity (rate of change per hour)
            time_window = 6  # hours
            shift_velocity = shift_magnitude / time_window
            
            # Estimate betting value potential
            # High shift + high trending = likely overreaction = value
            potential_value = shift_magnitude * (1.0 if recent_sentiment.trending else 0.5)
            
            return {
                'team': team,
                'shift_detected': shift_detected,
                'shift_magnitude': round(shift_magnitude, 3),
                'shift_direction': shift_direction,
                'shift_velocity': round(shift_velocity, 4),
                'potential_value': round(potential_value, 3),
                'recent_sample_size': recent_sentiment.sample_size,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Narrative shift detection failed: {e}")
            raise
