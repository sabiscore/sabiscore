"""
backend/src/models/bnn_ensemble_impl.py
Phase 6-A: Evidential Deep Learning BNN ensemble member (torch implementation).

Imported only when torch is available; the public bnn_ensemble.py wrapper
soft-fails to sentinels when torch is missing so the FastAPI app can still boot
without the BNN feature.

Implements Prior Networks (Malinin & Gales 2018) for Dirichlet-output
uncertainty decomposition. Single forward-pass — no MC overhead at inference.
MC-Dropout fallback class included for use if EDL fails ECE ≤ 0.050 gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor


# ─────────────────────────────────────────────────────────────────────────────
# Output data class (C12: epistemic_unc, aleatoric_unc, concentration,
#                         and credible_interval fields must all be present)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class UncertaintyOutput:
    """
    Full uncertainty decomposition from a single BNN forward pass.
    All scalar fields are plain Python floats (detached from autograd).
    """

    home_prob: float  # E[p_home] = alpha_home / alpha_0
    draw_prob: float  # E[p_draw]
    away_prob: float  # E[p_away]
    epistemic: float  # Σ_k Var[p_k] — bounded (0, 0.25)
    aleatoric: float  # H[E[p]] — bounded (0, log 3 ≈ 1.099)
    total: float  # epistemic + aleatoric
    concentration: float  # alpha_0 = Σ alpha_k (evidence strength)
    ci_lower: List[float]  # 95% CI lower [home, draw, away]
    ci_upper: List[float]  # 95% CI upper
    low_evidence: bool  # True when epistemic > EPISTEMIC_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# EDL BNN (Primary — Phase 6-A)
# Architecture: 58 → 256 (BN+GELU) → 128 (BN+GELU+Dropout) → 3
# Output: Dirichlet concentrations alpha [B, 3]
# ─────────────────────────────────────────────────────────────────────────────


class BNNEnsembleMember(nn.Module):
    """
    Evidential Deep Learning BNN member.
    Input:  [B, 58]  — CANONICAL_FEATURES_58 (C7 preserved; base-learner dims unchanged)
    Output: alpha    [B, 3] — Dirichlet concentrations {home, draw, away}

    Uncertainty decomposition is analytic (single pass):
      Epistemic : Σ_k alpha_k(alpha_0 − alpha_k) / (alpha_0² (alpha_0 + 1))
      Aleatoric : −Σ_k E[p_k] log(E[p_k])
    """

    def __init__(
        self,
        in_features: int = 58,
        hidden: int = 256,
        n_classes: int = 3,
        dropout_p: float = 0.10,
        eps: float = 1e-4,
    ) -> None:
        super().__init__()
        self.eps = eps
        self.n_classes = n_classes
        self.in_features = in_features

        self.net = nn.Sequential(
            nn.Linear(in_features, hidden),
            nn.BatchNorm1d(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden // 2),
            nn.BatchNorm1d(hidden // 2),
            nn.GELU(),
            nn.Dropout(p=dropout_p),
            nn.Linear(hidden // 2, n_classes),
        )

    def forward(self, x: Tensor) -> Tensor:
        """
        Args:
            x: [B, 58] normalised feature tensor
        Returns:
            alpha: [B, 3] Dirichlet concentrations, all > eps > 0
        """
        logits = self.net(x)
        return F.softplus(logits) + self.eps

    @torch.no_grad()
    def predict_uncertainty(
        self,
        x: Tensor,
        epistemic_threshold: float = 0.15,
        ci_samples: int = 200,
    ) -> List[UncertaintyOutput]:
        """
        Full analytic uncertainty decomposition — no MC sampling required.

        Epistemic variance (Dirichlet marginals):
            Var[p_k] = alpha_k (alpha_0 − alpha_k) / (alpha_0² (alpha_0 + 1))
        Aleatoric (entropy of mean distribution):
            H = −Σ_k E[p_k] log(E[p_k])
        Credible intervals: Dirichlet sample quantiles (lightweight, CPU).
        """
        self.eval()
        alpha = self(x)  # [B, 3]
        alpha_0 = alpha.sum(dim=1, keepdim=True)  # [B, 1]
        mean_p = alpha / alpha_0  # [B, 3]

        # Epistemic: sum of Dirichlet marginal variances
        var_k = (alpha * (alpha_0 - alpha)) / (alpha_0.pow(2) * (alpha_0 + 1.0))
        epistemic = var_k.sum(dim=1)  # [B]

        # Aleatoric: entropy of the mean predictive distribution
        aleatoric = -(mean_p * (mean_p + 1e-8).log()).sum(dim=1)  # [B]

        total = epistemic + aleatoric

        # 95% credible intervals via Dirichlet sampling (CPU, T=ci_samples)
        alpha_cpu = alpha.cpu()
        dirichlet = torch.distributions.Dirichlet(alpha_cpu)
        samples = dirichlet.sample((ci_samples,))  # [T, B, 3]
        ci_lower = samples.quantile(0.025, dim=0)  # [B, 3]
        ci_upper = samples.quantile(0.975, dim=0)  # [B, 3]

        results: List[UncertaintyOutput] = []
        for i in range(x.shape[0]):
            ep = float(epistemic[i])
            results.append(
                UncertaintyOutput(
                    home_prob=float(mean_p[i, 0]),
                    draw_prob=float(mean_p[i, 1]),
                    away_prob=float(mean_p[i, 2]),
                    epistemic=ep,
                    aleatoric=float(aleatoric[i]),
                    total=float(total[i]),
                    concentration=float(alpha_0[i, 0]),
                    ci_lower=ci_lower[i].tolist(),
                    ci_upper=ci_upper[i].tolist(),
                    low_evidence=ep > epistemic_threshold,
                )
            )
        return results

    @torch.no_grad()
    def get_meta_features(self, x: Tensor) -> Tensor:
        """Returns [B, 6] BNN meta-features for appending to the meta-learner stacking input.

        Feature order: [p_home, p_draw, p_away, epistemic, aleatoric, concentration]

        C7 constraint: CANONICAL_FEATURES_58 base-learner input is unchanged.
        This method is ONLY called during Phase 7+ retraining (bnn_meta_enabled=True).
        """
        self.eval()
        alpha = self(x)  # [B, 3]
        alpha_0 = alpha.sum(dim=1, keepdim=True)  # [B, 1]
        mean_p = alpha / alpha_0  # [B, 3]
        var_k = (alpha * (alpha_0 - alpha)) / (alpha_0.pow(2) * (alpha_0 + 1.0))
        epistemic = var_k.sum(dim=1, keepdim=True)  # [B, 1]
        aleatoric = -(mean_p * (mean_p + 1e-8).log()).sum(dim=1, keepdim=True)  # [B, 1]
        return torch.cat([mean_p, epistemic, aleatoric, alpha_0], dim=1)  # [B, 6]


# ─────────────────────────────────────────────────────────────────────────────
# MC-Dropout BNN (Fallback — used only if EDL ECE > 0.050 on validation set)
# ─────────────────────────────────────────────────────────────────────────────


class MCDropoutBNN(nn.Module):
    """
    MC-Dropout fallback BNN.
    Dropout is kept ACTIVE at inference time (T stochastic forward passes).

    Epistemic proxy : Var[p_k] across T samples
    Aleatoric proxy : mean per-sample entropy across T samples
    """

    def __init__(
        self,
        in_features: int = 58,
        hidden: int = 256,
        n_classes: int = 3,
        dropout_p: float = 0.15,
    ) -> None:
        super().__init__()
        self.n_classes = n_classes
        self.in_features = in_features
        self.dropout_p = dropout_p

        self.net = nn.Sequential(
            nn.Linear(in_features, hidden),
            nn.BatchNorm1d(hidden),
            nn.GELU(),
            nn.Dropout(p=dropout_p),
            nn.Linear(hidden, hidden // 2),
            nn.BatchNorm1d(hidden // 2),
            nn.GELU(),
            nn.Dropout(p=dropout_p),
            nn.Linear(hidden // 2, n_classes),
        )

    def forward(self, x: Tensor) -> Tensor:
        """Standard forward pass (softmax output for training with cross-entropy)."""
        return F.softmax(self.net(x), dim=-1)

    def predict_uncertainty_mc(
        self,
        x: Tensor,
        T: int = 50,
        epistemic_threshold: float = 0.15,
        ci_samples: int = 200,
    ) -> List[UncertaintyOutput]:
        """T stochastic forward passes with dropout active.

        The model is set to train() mode so dropout runs at inference.
        BN layers use running statistics (eval-like) to avoid batch issues.
        """
        # Keep BN in eval mode for stable statistics; Dropout needs train mode.
        for m in self.modules():
            if isinstance(m, nn.BatchNorm1d):
                m.eval()
            elif isinstance(m, nn.Dropout):
                m.train()

        with torch.no_grad():
            all_probs: List[Tensor] = []
            for _ in range(T):
                logits = self.net(x)  # [B, 3]
                probs = F.softmax(logits, dim=-1)  # [B, 3]
                all_probs.append(probs)

        stacked = torch.stack(all_probs, dim=0)  # [T, B, 3]
        mean_p = stacked.mean(dim=0)  # [B, 3]

        # Epistemic proxy: predictive variance across samples
        var_p = stacked.var(dim=0)  # [B, 3]
        epistemic = var_p.sum(dim=1)  # [B]

        # Aleatoric proxy: mean of per-sample entropies
        per_sample_entropy = -(stacked * (stacked + 1e-8).log()).sum(dim=2)  # [T, B]
        aleatoric = per_sample_entropy.mean(dim=0)  # [B]

        total = epistemic + aleatoric

        # Credible intervals via sample quantiles
        ci_lower = stacked.quantile(0.025, dim=0)  # [B, 3]
        ci_upper = stacked.quantile(0.975, dim=0)  # [B, 3]

        results: List[UncertaintyOutput] = []
        for i in range(x.shape[0]):
            ep = float(epistemic[i])
            results.append(
                UncertaintyOutput(
                    home_prob=float(mean_p[i, 0]),
                    draw_prob=float(mean_p[i, 1]),
                    away_prob=float(mean_p[i, 2]),
                    epistemic=ep,
                    aleatoric=float(aleatoric[i]),
                    total=float(total[i]),
                    concentration=0.0,  # not applicable to MC-Dropout
                    ci_lower=ci_lower[i].tolist(),
                    ci_upper=ci_upper[i].tolist(),
                    low_evidence=ep > epistemic_threshold,
                )
            )
        return results

    @torch.no_grad()
    def get_meta_features(self, x: Tensor, T: int = 10) -> Tensor:
        """Returns [B, 6] meta-features from MC mean and variance for stacking.

        Feature order: [p_home, p_draw, p_away, epistemic, aleatoric, 0.0]
        Last column is 0 (no concentration estimate for MC-Dropout).
        """
        for m in self.modules():
            if isinstance(m, nn.BatchNorm1d):
                m.eval()
            elif isinstance(m, nn.Dropout):
                m.train()

        stacked = torch.stack(
            [F.softmax(self.net(x), dim=-1) for _ in range(T)], dim=0
        )  # [T, B, 3]
        mean_p = stacked.mean(dim=0)  # [B, 3]
        var_p = stacked.var(dim=0).sum(dim=1, keepdim=True)  # [B, 1] — epistemic proxy
        per_entropy = -(stacked * (stacked + 1e-8).log()).sum(dim=2)
        aleatoric = per_entropy.mean(dim=0, keepdim=True).T  # [B, 1]
        zeros = torch.zeros(x.shape[0], 1, device=x.device)
        return torch.cat([mean_p, var_p, aleatoric, zeros], dim=1)  # [B, 6]


# ─────────────────────────────────────────────────────────────────────────────
# EDL training loss — Sensoy et al. 2018 (Equations 3 + 5)
# ─────────────────────────────────────────────────────────────────────────────


def edl_nll_loss(
    alpha: Tensor,
    y: Tensor,
    epoch: int,
    lambda_kl_max: float = 0.01,
    warmup_epochs: int = 100,
) -> Tensor:
    """Annealed EDL negative log-likelihood loss.

    Args:
        alpha  : [B, K] Dirichlet concentration parameters (output of BNNEnsembleMember)
        y      : [B, K] one-hot class labels (float)
        epoch  : current training epoch (0-indexed), used for KL annealing coefficient
        lambda_kl_max  : maximum KL weight after warmup (default 0.01)
        warmup_epochs  : number of epochs over which lambda ramps from 0 → lambda_kl_max

    Returns:
        scalar loss tensor
    """
    K = alpha.shape[1]
    alpha_0 = alpha.sum(dim=1, keepdim=True)  # [B, 1]

    # ── NLL term (Sensoy et al. 2018, Eq. 5) ────────────────────────────────
    # E_{p~Dir(alpha)}[log p(y|p)] = Σ_k y_k (ψ(alpha_k) − ψ(alpha_0))
    nll_mean = -(y * (torch.digamma(alpha) - torch.digamma(alpha_0))).sum(dim=1).mean()

    # ── KL regularisation (Sensoy Eq. 5) ─────────────────────────────────────
    # Remove evidence for wrong classes to avoid over-regularising correct class
    alpha_tilde = y + (1.0 - y) * alpha  # [B, K]
    alpha_tilde_0 = alpha_tilde.sum(dim=1, keepdim=True)  # [B, 1]
    ones = torch.ones_like(alpha_tilde)

    # KL[ Dir(alpha_tilde) || Dir(1,...,1) ]
    kl = (
        torch.lgamma(alpha_tilde_0)
        - math.lgamma(K)
        - torch.lgamma(alpha_tilde).sum(dim=1, keepdim=True)
        + (
            (alpha_tilde - ones)
            * (torch.digamma(alpha_tilde) - torch.digamma(alpha_tilde_0))
        ).sum(dim=1, keepdim=True)
    )
    kl_mean = kl.squeeze(1).mean()

    # ── Annealed coefficient λ(t) = min(1.0, t / warmup_epochs) × lambda_kl_max ──
    lambda_t = min(1.0, epoch / max(warmup_epochs, 1)) * lambda_kl_max

    return nll_mean + lambda_t * kl_mean
