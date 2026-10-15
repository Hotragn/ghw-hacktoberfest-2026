SET search_path TO scamshield, public;
SELECT add_continuous_aggregate_policy('signals_hourly', start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '5 minutes', if_not_exists => true);
SELECT add_continuous_aggregate_policy('tx_daily',       start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '10 minutes', if_not_exists => true);
SELECT add_continuous_aggregate_policy('btc_1m',         start_offset => INTERVAL '1 day',  end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute', if_not_exists => true);

CALL remove_columnstore_policy('home_signals', if_exists => true);
CALL add_columnstore_policy('home_signals', after => INTERVAL '1 day');
CALL remove_columnstore_policy('transactions', if_exists => true);
CALL add_columnstore_policy('transactions', after => INTERVAL '7 days');
CALL remove_columnstore_policy('btc_ticks', if_exists => true);
CALL add_columnstore_policy('btc_ticks', after => INTERVAL '1 day');

-- Data minimisation: raw in-home signals are kept only 30 days; hourly rollups 180 days.
SELECT add_retention_policy('home_signals',   drop_after => INTERVAL '30 days',  if_not_exists => true);
SELECT add_retention_policy('profit_claims',  drop_after => INTERVAL '90 days',  if_not_exists => true);
SELECT add_retention_policy('btc_ticks',      drop_after => INTERVAL '90 days',  if_not_exists => true);
SELECT add_retention_policy('signals_hourly', drop_after => INTERVAL '180 days', if_not_exists => true);
