# Live Model (v4_oos_2025)

Place the v4_oos_2025 model artifacts here for `--live` mode:

```
NIFTY_direction.joblib
NIFTY_phase1_target.joblib
NIFTY_selected_features.json
NIFTY_sl_bin.joblib
NIFTY_sl_bin_encoder.joblib
NIFTY_trade_class.joblib
NIFTY_trade_class_encoder.joblib
NIFTY_trail_bin.joblib
NIFTY_trail_bin_encoder.joblib
NIFTY_trail_tf.joblib
NIFTY_trail_tf_encoder.joblib
NIFTY_train_metrics.json
model_version.json
```

Copy from EC2 (wherever v4_oos_2025 was last deployed):
```bash
cp /path/to/v4_oos_2025/artifacts/* models/live/
```
