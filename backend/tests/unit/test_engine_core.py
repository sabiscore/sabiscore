import types
from unittest.mock import MagicMock, patch


def test_engine_basic_flow():
    """Test core engine workflow with injected mocks"""
    sklearn_module = types.ModuleType('sklearn')
    sklearn_ensemble = types.ModuleType('sklearn.ensemble')
    sklearn_linear = types.ModuleType('sklearn.linear_model')
    sklearn_model_selection = types.ModuleType('sklearn.model_selection')
    sklearn_metrics = types.ModuleType('sklearn.metrics')
    sklearn_preprocessing = types.ModuleType('sklearn.preprocessing')

    sklearn_ensemble.RandomForestClassifier = MagicMock()
    sklearn_ensemble.GradientBoostingClassifier = MagicMock()
    sklearn_linear.LogisticRegression = MagicMock()
    sklearn_model_selection.train_test_split = MagicMock(return_value=([], [], [], []))
    sklearn_metrics.accuracy_score = MagicMock(return_value=0.0)
    sklearn_metrics.brier_score_loss = MagicMock(return_value=0.0)
    sklearn_metrics.log_loss = MagicMock(return_value=0.0)
    sklearn_preprocessing.StandardScaler = MagicMock(return_value=MagicMock())

    torch_module = types.ModuleType('torch')
    xgboost_module = types.ModuleType('xgboost')
    xgboost_module.XGBClassifier = MagicMock()
    lightgbm_module = types.ModuleType('lightgbm')
    lightgbm_module.LGBMClassifier = MagicMock()
    scipy_module = types.ModuleType('scipy')
    numpy_module = types.ModuleType('numpy')
    numpy_random = types.SimpleNamespace(
        seed=lambda *_: None,
        random=lambda: 0.1,
    )
    numpy_module.__version__ = '1.0'
    numpy_module.random = numpy_random
    pandas_module = types.ModuleType('pandas')
    pandas_dataframe_cls = MagicMock()
    pandas_series_cls = MagicMock()
    pandas_module.DataFrame = pandas_dataframe_cls
    pandas_module.Series = pandas_series_cls
    pandas_module.concat = MagicMock()

    ge_module = types.ModuleType('great_expectations')
    ge_dataset_module = types.ModuleType('great_expectations.dataset')
    ge_dataset_module.PandasDataset = MagicMock()

    with patch.dict('sys.modules', {
        'numpy': numpy_module,
        'pandas': pandas_module,
        'sklearn': sklearn_module,
        'sklearn.ensemble': sklearn_ensemble,
        'sklearn.linear_model': sklearn_linear,
        'sklearn.model_selection': sklearn_model_selection,
        'sklearn.metrics': sklearn_metrics,
        'sklearn.preprocessing': sklearn_preprocessing,
        'torch': torch_module,
        'xgboost': xgboost_module,
        'lightgbm': lightgbm_module,
        'scipy': scipy_module,
        'great_expectations': ge_module,
        'great_expectations.dataset': ge_dataset_module,
    }):
        from src.insights.engine import InsightsEngine

    mock_aggregator = MagicMock()
    mock_model = MagicMock()
    transformer_mock = MagicMock()
    transformer_mock.engineer_features.return_value = {}
    explainer_mock = MagicMock()
    explainer_mock.explain_prediction.return_value = {}

    mock_aggregator.fetch_match_data.return_value = {
        'metadata': {
            'matchup': 'TeamA vs TeamB',
            'league': 'EPL',
        },
        'team_stats': {
            'home': {
                'attacking_strength': 0.9,
                'defensive_strength': 0.8,
            },
            'away': {
                'attacking_strength': 0.7,
                'defensive_strength': 0.75,
            },
        },
        'odds': {
            'home_win': 2.1,
            'draw': 3.5,
            'away_win': 3.9,
        }
    }
    mock_model.is_trained = False

    engine = InsightsEngine(
        model=mock_model,
        aggregator=mock_aggregator,
        transformer=transformer_mock,
        explainer=explainer_mock,
    )

    result = engine.generate_match_insights('TeamA vs TeamB', 'EPL')

    assert isinstance(result, dict)
    assert result['metadata']['matchup'] == 'TeamA vs TeamB'
    assert result['predictions']['prediction'] == 'home_win'
    mock_aggregator.fetch_match_data.assert_called_once()
    transformer_mock.engineer_features.assert_called_once()
