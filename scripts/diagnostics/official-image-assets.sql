-- Self-hosted official image rows: totals and mirror activity by day (insert-only table).
-- totals
select count(*) n, count(distinct card_print_id) prints, sum(byte_size) bytes,
  min(mirrored_at) first_mirrored_at, max(mirrored_at) last_mirrored_at
from card_print_image_assets;

-- by_day
select date_trunc('day', mirrored_at) day_utc, count(*) n, sum(byte_size) bytes
from card_print_image_assets group by 1 order by 1 desc limit 14;
