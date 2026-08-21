select metric_date, merchant_category, count(*)
from {{ ref('mart_daily_segment_kpis') }}
group by 1, 2
having count(*) > 1
