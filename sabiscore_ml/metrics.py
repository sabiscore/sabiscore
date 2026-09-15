import numpy as np

def multiclass_brier_score(y_true, y_prob):
    """
    Computes the multiclass Brier Score.
    Measures the mean squared difference between predicted probabilities 
    and the actual outcome (one-hot encoded).
    NOTE: Multiclass Brier scores range from 0 to 2, not 0 to 1.
    """
    # 1. Create a one-hot encoded matrix for the true targets
    y_true_arr = np.array(y_true).astype(int)
    y_true_one_hot = np.zeros_like(y_prob)
    y_true_one_hot[np.arange(len(y_true_arr)), y_true_arr] = 1.0
    
    # 2. Calculate sum of squared errors across all 3 classes, then average
    return np.mean(np.sum((y_true_one_hot - y_prob)**2, axis=1))

def classwise_ece(y_true, y_prob, n_bins=10):
    """
    Computes the Macro-Averaged Expected Calibration Error for 1X2 outcomes.
    Calculates the binary ECE for Home, Draw, and Away, then averages them.
    """
    n_classes = y_prob.shape[1]
    y_true_arr = np.array(y_true).astype(int)
    ece_per_class = []
    
    bins = np.linspace(0., 1., n_bins + 1)
    
    for c in range(n_classes):
        # Isolate the current class (e.g., Home Win = 0)
        y_true_binary = (y_true_arr == c).astype(int)
        y_prob_c = y_prob[:, c]
        
        binids = np.digitize(y_prob_c, bins) - 1
        
        ece = 0
        for i in range(n_bins):
            mask = (binids == i)
            if np.sum(mask) > 0:
                prob_pred_mean = np.mean(y_prob_c[mask])
                prob_true_mean = np.mean(y_true_binary[mask])
                # Weighted absolute difference
                ece += np.abs(prob_true_mean - prob_pred_mean) * np.sum(mask)
                
        ece_per_class.append(ece / len(y_prob_c))
        
    return np.mean(ece_per_class)
