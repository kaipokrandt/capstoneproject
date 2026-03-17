python3 generator_v2.py --scenario walk --seconds 30 --hz 100 --out_bin walk.bin --out_csv walk.csv --out_ndjson walk.ndjson
python3 backend_v2.py replay walk.bin --db wearble.db --out_ndjson walk_events.ndjson
