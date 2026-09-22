"""
Vector embeddings system for similar match clustering and creative prediction enhancement.
Uses sentence transformers to find historical analogs for novel situations.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pickle

logger = logging.getLogger(__name__)


class MatchVectorEmbeddings:
    """
    Vector embeddings for match similarity and creative prediction:
    - Embed matches into 384-dim vector space
    - Find similar historical matches (K-NN)
    - Augment predictions with analogous outcomes
    - Detect rare/novel situations requiring special handling

    Creative Applications:
    - "This Liverpool defense vs Salah's form is similar to 2019 Bayern vs Lewandowski"
    - "Man City's injuries mirror Arsenal 2022 → expect defensive regression"
    - "This refereeing style + weather = historically low-scoring"
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.redis = redis_client
        self.model_name = embedding_model
        self.model = None
        self.embedding_dim = 384
        self.cache_ttl = 86400  # 24 hours

        # Initialize model lazily
        self._init_model()

        logger.info(f"MatchVectorEmbeddings initialized with {embedding_model}")

    def _init_model(self):
        """Initialize sentence transformer model"""
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name)
            logger.info("Sentence transformer model loaded successfully")
        except ImportError:
            logger.warning("sentence-transformers not installed. Using placeholder.")
            self.model = None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.model = None

    def create_match_descriptor(
        self,
        match_data: Dict[str, Any],
    ) -> str:
        """
        Create natural language descriptor for match embedding.

        This is the creative part - we describe the match context in a way
        that captures tactical, form, and situational similarities.

        Example output:
        "Liverpool attacking team with high press (PPDA 8.2) faces defensive
        Brighton (low block, 35% possession). Liverpool in excellent form (5 wins)
        but missing key midfielder Thiago. Referee Mike Dean strict (4.2 cards/game).
        Weather rainy which reduces xG by 8%. Home advantage strong (12th man effect).
        Historical H2H: Liverpool dominates 8-2-0."
        """
        parts = []

        # Team styles
        home_team = match_data.get("home_team", "Home")
        away_team = match_data.get("away_team", "Away")

        home_style = self._describe_team_style(match_data.get("home_tactics", {}))
        away_style = self._describe_team_style(match_data.get("away_tactics", {}))

        parts.append(f"{home_team} {home_style} faces {away_team} {away_style}")

        # Form
        home_form = match_data.get("home_form", {})
        away_form = match_data.get("away_form", {})

        parts.append(self._describe_form(home_team, home_form))
        parts.append(self._describe_form(away_team, away_form))

        # Injuries/Absences
        home_injuries = match_data.get("home_injuries", [])
        away_injuries = match_data.get("away_injuries", [])

        if home_injuries:
            parts.append(f"{home_team} missing {len(home_injuries)} key players")
        if away_injuries:
            parts.append(f"{away_team} missing {len(away_injuries)} key players")

        # Context factors
        referee = match_data.get("referee", {})
        if referee:
            parts.append(
                f"Referee {referee.get('name', 'unknown')} "
                f"({referee.get('avg_cards', 0):.1f} cards/game)"
            )

        weather = match_data.get("weather", {})
        if weather and weather.get("condition") != "clear":
            parts.append(f"Weather {weather.get('condition', 'unknown')}")

        # H2H
        h2h = match_data.get("head_to_head", {})
        if h2h:
            parts.append(
                f"H2H: {home_team} {h2h.get('home_wins', 0)}-"
                f"{h2h.get('draws', 0)}-{h2h.get('away_wins', 0)}"
            )

        return ". ".join(parts)

    def _describe_team_style(self, tactics: Dict[str, Any]) -> str:
        """Describe team tactical style"""
        if not tactics:
            return "balanced team"

        ppda = tactics.get("ppda", 10.0)
        possession = tactics.get("possession_pct", 50.0)

        if ppda < 8 and possession > 55:
            return "high-press attacking team"
        elif ppda < 8:
            return "aggressive pressing team"
        elif possession > 60:
            return "possession-dominant team"
        elif possession < 40:
            return "counter-attacking team"
        else:
            return "balanced team"

    def _describe_form(self, team: str, form: Dict[str, Any]) -> str:
        """Describe team form"""
        if not form:
            return f"{team} in average form"

        wins = form.get("wins_last_5", 0)

        if wins >= 4:
            return f"{team} in excellent form ({wins} wins in last 5)"
        elif wins >= 3:
            return f"{team} in good form ({wins} wins)"
        elif wins <= 1:
            return f"{team} struggling (only {wins} wins)"
        else:
            return f"{team} in average form"

    def embed_match(
        self,
        match_data: Dict[str, Any],
    ) -> np.ndarray:
        """
        Convert match to vector embedding.

        Args:
            match_data: Match context (teams, tactics, form, injuries, etc.)

        Returns:
            384-dim embedding vector
        """
        try:
            # Create descriptor
            descriptor = self.create_match_descriptor(match_data)

            # Generate embedding
            if self.model:
                embedding = self.model.encode(descriptor)
                return embedding
            else:
                # Placeholder: return random vector
                return np.random.randn(self.embedding_dim)

        except Exception as e:
            logger.error(f"Failed to embed match: {e}")
            return np.zeros(self.embedding_dim)

    async def find_similar_matches(
        self,
        match_embedding: np.ndarray,
        historical_embeddings: List[Tuple[str, np.ndarray, Dict]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Find K most similar historical matches using cosine similarity.

        Args:
            match_embedding: Query match embedding
            historical_embeddings: List of (match_id, embedding, outcome)
            top_k: Number of similar matches to return

        Returns:
            List of similar matches with outcomes:
            [
                {
                    'match_id': str,
                    'similarity': float,
                    'outcome': Dict,  # Result, xG, etc.
                    'descriptor': str,
                },
                ...
            ]
        """
        similarities = []

        for match_id, hist_embedding, outcome in historical_embeddings:
            # Cosine similarity
            similarity = self._cosine_similarity(match_embedding, hist_embedding)
            similarities.append(
                {
                    "match_id": match_id,
                    "similarity": float(similarity),
                    "outcome": outcome,
                }
            )

        # Sort by similarity
        similarities.sort(key=lambda x: x["similarity"], reverse=True)

        return similarities[:top_k]

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    async def augment_prediction_with_analogs(
        self,
        base_prediction: float,
        similar_matches: List[Dict[str, Any]],
        confidence_threshold: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Augment base model prediction with similar match outcomes.

        Creative logic:
        - If similar matches strongly agree (>70% same outcome), boost confidence
        - If novel situation (low similarity), flag for manual review
        - Weight by both similarity and recency

        Args:
            base_prediction: Base model probability (0-1)
            similar_matches: Similar historical matches with outcomes
            confidence_threshold: Min similarity to include in ensemble

        Returns:
            Dict with augmented prediction:
            {
                'base_prediction': float,
                'analog_prediction': float,
                'final_prediction': float,
                'confidence_boost': float,
                'novel_situation': bool,
                'supporting_analogs': int,
            }
        """
        if not similar_matches:
            return {
                "base_prediction": base_prediction,
                "analog_prediction": base_prediction,
                "final_prediction": base_prediction,
                "confidence_boost": 0.0,
                "novel_situation": True,
                "supporting_analogs": 0,
            }

        # Filter by confidence threshold
        confident_analogs = [
            m for m in similar_matches if m["similarity"] >= confidence_threshold
        ]

        # Check for novel situation
        novel_situation = (
            len(confident_analogs) < 3
            or max(m["similarity"] for m in similar_matches) < 0.6
        )

        if not confident_analogs:
            return {
                "base_prediction": base_prediction,
                "analog_prediction": base_prediction,
                "final_prediction": base_prediction,
                "confidence_boost": 0.0,
                "novel_situation": True,
                "supporting_analogs": 0,
            }

        # Calculate weighted average of analog outcomes
        weights = []
        outcomes = []

        for match in confident_analogs:
            weight = match["similarity"]

            # Boost weight for recent matches (recency bias)
            if "date" in match["outcome"]:
                # Decay factor: 0.95^(months_ago)
                # For now, use uniform weights
                pass

            weights.append(weight)

            # Extract outcome probability
            # Assuming outcome has home_win_prob or similar
            outcome_prob = match["outcome"].get("home_win_prob", 0.5)
            outcomes.append(outcome_prob)

        # Weighted average
        analog_prediction = np.average(outcomes, weights=weights)

        # Blend with base model (70/30 split)
        final_prediction = 0.7 * base_prediction + 0.3 * analog_prediction

        # Calculate confidence boost
        # High agreement + high similarity = confidence boost
        agreement = 1.0 - np.std(outcomes)  # Low std = high agreement
        avg_similarity = np.mean([m["similarity"] for m in confident_analogs])
        confidence_boost = agreement * avg_similarity

        return {
            "base_prediction": float(base_prediction),
            "analog_prediction": float(analog_prediction),
            "final_prediction": float(final_prediction),
            "confidence_boost": float(confidence_boost),
            "novel_situation": novel_situation,
            "supporting_analogs": len(confident_analogs),
            "avg_analog_similarity": float(avg_similarity),
        }

    async def cache_embedding(
        self,
        match_id: str,
        embedding: np.ndarray,
    ):
        """Cache embedding in Redis"""
        if not self.redis:
            return

        try:
            # Serialize embedding
            embedding_bytes = pickle.dumps(embedding)

            # Cache
            cache_key = f"embedding:{match_id}"
            await self.redis.setex(cache_key, self.cache_ttl, embedding_bytes)

        except Exception as e:
            logger.error(f"Failed to cache embedding: {e}")

    async def get_cached_embedding(
        self,
        match_id: str,
    ) -> Optional[np.ndarray]:
        """Get cached embedding from Redis"""
        if not self.redis:
            return None

        try:
            cache_key = f"embedding:{match_id}"
            cached = await self.redis.get(cache_key)

            if cached:
                embedding = pickle.loads(cached)
                return embedding

        except Exception as e:
            logger.error(f"Failed to retrieve cached embedding: {e}")

        return None

    def detect_outliers(
        self,
        match_embedding: np.ndarray,
        historical_embeddings: List[np.ndarray],
        threshold: float = 2.0,
    ) -> bool:
        """
        Detect if match is an outlier (novel/rare situation).
        Uses Mahalanobis distance or simple distance threshold.

        Args:
            match_embedding: Query embedding
            historical_embeddings: Historical embedding vectors
            threshold: Distance threshold (std devs)

        Returns:
            True if outlier, False otherwise
        """
        if not historical_embeddings or len(historical_embeddings) < 10:
            return True  # Not enough history

        try:
            # Calculate distance to nearest neighbor
            min_distance = float("inf")

            for hist_emb in historical_embeddings:
                dist = np.linalg.norm(match_embedding - hist_emb)
                min_distance = min(min_distance, dist)

            # Calculate mean and std of historical distances
            historical_dist_matrix = []
            for i, emb1 in enumerate(historical_embeddings):
                for emb2 in historical_embeddings[i + 1 :]:
                    dist = np.linalg.norm(emb1 - emb2)
                    historical_dist_matrix.append(dist)

            mean_dist = np.mean(historical_dist_matrix)
            std_dist = np.std(historical_dist_matrix)

            # Z-score
            z_score = (min_distance - mean_dist) / std_dist if std_dist > 0 else 0

            return z_score > threshold

        except Exception as e:
            logger.error(f"Outlier detection failed: {e}")
            return False
