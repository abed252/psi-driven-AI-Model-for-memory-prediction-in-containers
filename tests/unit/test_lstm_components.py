"""LSTM building blocks: normalizer discipline, variant selection,
reproducible initialization. No dataset files needed."""

import numpy as np
import pytest

from psi_memory.dataset.signals import ALL_SIGNALS, NO_PSI_SIGNALS, PSI_SIGNALS
from psi_memory.models.lstm import Normalizer, build_model, variant_signal_indices

SCHEMA = {"no_psi_signals": NO_PSI_SIGNALS, "psi_signals": PSI_SIGNALS}


def test_variant_selection_no_psi_excludes_psi_columns():
    indices, names = variant_signal_indices(ALL_SIGNALS, SCHEMA, "no_psi")
    assert names == NO_PSI_SIGNALS
    assert not set(names) & set(PSI_SIGNALS)
    assert [ALL_SIGNALS[i] for i in indices] == names


def test_variant_selection_with_psi_appends_only_psi():
    _, no_psi_names = variant_signal_indices(ALL_SIGNALS, SCHEMA, "no_psi")
    _, with_psi_names = variant_signal_indices(ALL_SIGNALS, SCHEMA, "with_psi")
    assert with_psi_names[:len(no_psi_names)] == no_psi_names
    assert with_psi_names[len(no_psi_names):] == PSI_SIGNALS


def test_variant_selection_missing_signal_raises():
    with pytest.raises(ValueError, match="lacks signals"):
        variant_signal_indices(["current_mib"], SCHEMA, "no_psi")


def test_normalizer_uses_train_statistics_only():
    rng = np.random.default_rng(0)
    X_train = rng.normal(5.0, 2.0, size=(50, 10, 3)).astype(np.float32)
    y_train = rng.normal(100.0, 10.0, size=50).astype(np.float32)
    normalizer = Normalizer(X_train, y_train)
    np.testing.assert_allclose(normalizer.mean, X_train.mean(axis=(0, 1)),
                               rtol=1e-5)
    # Transforming train data yields ~zero mean / unit std per signal.
    transformed = normalizer.transform(X_train)
    np.testing.assert_allclose(transformed.mean(axis=(0, 1)), 0.0, atol=1e-4)
    np.testing.assert_allclose(transformed.std(axis=(0, 1)), 1.0, atol=1e-3)
    # Data from a different distribution is NOT re-centered to zero.
    X_other = rng.normal(500.0, 2.0, size=(20, 10, 3)).astype(np.float32)
    assert abs(normalizer.transform(X_other).mean()) > 10


def test_normalizer_y_round_trip():
    rng = np.random.default_rng(1)
    y = rng.uniform(40, 250, 100).astype(np.float32)
    normalizer = Normalizer(rng.normal(size=(10, 5, 2)).astype(np.float32), y)
    np.testing.assert_allclose(normalizer.invert_y(normalizer.transform_y(y)),
                               y, rtol=1e-5)


def test_normalizer_zero_variance_signal_is_safe():
    X = np.ones((20, 10, 2), dtype=np.float32)
    normalizer = Normalizer(X, np.ones(20, dtype=np.float32))
    transformed = normalizer.transform(X)
    assert np.isfinite(transformed).all()


def test_reproducible_initialization():
    import torch

    from psi_memory.common.seed import seed_everything

    config = {"hidden_size": 16, "num_layers": 1, "dropout": 0.0}
    seed_everything(123)
    model_a = build_model(8, config)
    seed_everything(123)
    model_b = build_model(8, config)
    for (name_a, p_a), (name_b, p_b) in zip(model_a.named_parameters(),
                                            model_b.named_parameters()):
        assert name_a == name_b
        assert torch.equal(p_a, p_b), f"parameter {name_a} differs"


def test_model_output_shape():
    import torch

    model = build_model(8, {"hidden_size": 16, "num_layers": 2, "dropout": 0.1})
    out = model(torch.zeros(4, 30, 8))
    assert out.shape == (4,)
