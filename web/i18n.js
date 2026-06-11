/* ============================================================================
 * Quant Research — internationalization layer (FA / EN)
 * ----------------------------------------------------------------------------
 * Single source of truth for every user-facing string. Static markup uses
 * data-i18n / data-i18n-html / data-i18n-ph / data-i18n-title attributes;
 * dynamically rendered markup calls t('key', {params}). Backend payloads carry
 * language-neutral *codes* (regime, recommendation reasons, ML/RL hints, job
 * messages) which are resolved here so no Persian can ever leak in EN mode.
 * ========================================================================== */

const I18N = {
  fa: {
    /* ── brand / chrome ───────────────────────────────────────────── */
    brand: 'QuantResearch',
    brand_tagline: 'پلتفرم ریسرچ کوانت',
    version_label: 'نسخهٔ ۱.۲',
    theme_aurora: 'Midnight Aurora',

    /* ── navigation ───────────────────────────────────────────────── */
    nav_download: 'دانلود داده',
    nav_inventory: 'گزارش داده',
    nav_research: 'ریسرچ',
    nav_report: 'ریپورت',
    nav_insights: 'اینسایت',
    nav_lab: 'آزمایشگاه',
    nav_edges: 'لبه‌ها',
    nav_logs: 'لاگ‌ها',

    /* ── section titles + subtitles ───────────────────────────────── */
    title_download: 'دانلود داده', sub_download: 'دریافت داده از صرافی‌ها',
    title_inventory: 'گزارش داده', sub_inventory: 'داده‌های موجود در سیستم',
    title_research: 'ریسرچ', sub_research: 'اجرای بک‌تست استراتژی‌ها',
    title_report: 'ریپورت', sub_report: 'نتایج تحلیل کوانت',
    title_insights: 'اینسایت', sub_insights: 'پیشنهاد بهترین استراتژی',
    title_lab: 'آزمایشگاه', sub_lab: 'کاستومایز و بهینه‌سازی استراتژی',
    title_edges: 'لبه‌های معتبر', sub_edges: 'لبه‌های اعتبارسنجی‌شدهٔ walk-forward',
    title_logs: 'لاگ‌های سیستم', sub_logs: 'رویدادهای داخلی پلتفرم',

    /* ── common ───────────────────────────────────────────────────── */
    refresh: 'رفرش', reload: 'بارگیری', back: 'بازگشت', run: 'اجرا',
    loading: 'در حال بارگذاری…', error: 'خطا', error_colon: 'خطا: ',
    no_data: 'داده‌ای یافت نشد', insufficient_data: 'داده کافی نیست',
    candles: 'کندل', delete_file: 'حذف فایل', search: 'جستجو…',
    all_exchanges: 'همه صرافی‌ها', all_levels: 'همه سطوح',
    select_placeholder: 'انتخاب…', progress: 'پیشرفت',
    benchmark: 'بنچمارک', zero: 'صفر', average: 'میانگین', normal_dist: 'توزیع نرمال',

    /* ── download section ─────────────────────────────────────────── */
    dl_settings: 'تنظیمات دانلود',
    dl_exchange: 'صرافی',
    dl_symbol: 'جفت ارز / نماد',
    dl_symbol_ph: 'مثال: BTCUSDT',
    dl_symbol_select_ph: 'انتخاب نماد…',
    dl_symbol_toggle: 'سوییچ بین لیست و دستی',
    dl_loading_symbols: 'در حال بارگذاری نمادها…',
    dl_range: 'بازه زمانی',
    dl_from: 'از تاریخ', dl_to: 'تا تاریخ',
    dl_market: 'نوع بازار',
    dl_market_spot: 'اسپات', dl_market_futures: 'فیوچرز / پرپ',
    dl_timeframes: 'تایم‌فریم‌ها',
    dl_start_btn: 'شروع دانلود',
    dl_downloading: 'در حال دانلود…',
    dl_history: 'تاریخچه دانلودها',
    dl_history_empty: 'هنوز دانلودی انجام نشده',
    dl_fill_all: 'لطفاً همه فیلدها را پر کنید',

    /* ── inventory section ────────────────────────────────────────── */
    inv_summary: 'خلاصه داده‌های موجود',
    inv_files: 'فایل‌های پارکت',
    inv_metric_files: 'فایل‌ها', inv_metric_candles: 'کندل‌ها',
    inv_metric_exchanges: 'صرافی‌ها', inv_metric_symbols: 'نمادها',
    inv_metric_disk: 'حجم دیسک',
    inv_confirm_delete: 'حذف «{file}»؟\nاین عملیات قابل بازگشت نیست.',
    inv_delete_failed: 'خطا در حذف: ',

    /* ── research section ─────────────────────────────────────────── */
    res_select_data: 'انتخاب داده',
    res_datasets_label: 'دیتاست‌ها (چند انتخابی)',
    res_selected_count: '{n} دیتاست انتخاب شده',
    res_date_filter: 'فیلتر بازه زمانی (اختیاری)',
    res_bt_settings: 'تنظیمات بک‌تست',
    res_capital: 'سرمایه اولیه ($)',
    res_return_type: 'نوع بازده',
    res_simple: 'ساده', res_log: 'لگاریتمی',
    res_fee: 'کارمزد (bps)', res_slippage: 'اسلیپیج (bps)',
    res_strategies: 'استراتژی‌ها',
    res_run_btn: 'اجرای ریسرچ',
    res_running: 'در حال اجرا…',
    res_need_dataset: 'حداقل یک دیتاست انتخاب کنید',
    res_need_strategy: 'حداقل یک استراتژی انتخاب کنید',

    /* ── report section ───────────────────────────────────────────── */
    rep_empty_title: 'ابتدا یک ریسرچ اجرا کنید',
    rep_empty_sub: 'به بخش ریسرچ بروید و بک‌تست را اجرا کنید',
    rep_select_dataset: 'انتخاب دیتاست برای نمایش',
    rep_tab_equity: 'نمودار سهام', rep_tab_drawdown: 'افت سرمایه',
    rep_tab_monthly: 'بازده ماهانه', rep_tab_rolling: 'شارپ غلتان',
    rep_tab_distribution: 'توزیع بازده', rep_tab_metrics: 'جدول متریک‌ها',
    rep_equity_curve: 'منحنی سهام (Equity Curve)',
    rep_show_regime: 'نمایش رژیم',
    rep_drawdown: 'افت از اوج (Drawdown)',
    rep_monthly: 'بازده ماهانه (Heatmap)',
    rep_rolling: 'شارپ غلتان (۳۰ کندل)',
    rep_distribution: 'توزیع بازده (Return Distribution)',
    rep_metrics_full: 'جدول متریک‌های کامل',
    rep_portfolio_value: 'ارزش پرتفوی ($)',
    rep_count: 'تعداد', rep_count_times: 'بار',
    rep_metric: 'متریک',
    m_total_return: 'بازده کل', m_cagr: 'CAGR', m_sharpe: 'شارپ',
    m_sortino: 'سورتینو', m_calmar: 'کالمار', m_max_dd: 'حداکثر افت',
    m_profit_factor: 'فاکتور سود', m_win_rate: 'نرخ برد',
    stat_mean: 'میانگین', stat_std: 'انحراف معیار',
    stat_skew: 'چولگی', stat_kurt: 'کشیدگی',

    /* ── insights section ─────────────────────────────────────────── */
    ins_select_dataset: 'انتخاب دیتاست برای آنالیز عمیق',
    ins_intro: 'یک دیتاست را انتخاب کنید تا تحلیل کامل استراتژی‌ها، چرخش رژیم و oracle equity نمایش داده شود.',
    ins_loading_datasets: 'در حال بارگذاری دیتاست‌ها…',
    ins_click_to_analyze: 'کلیک برای تحلیل عمیق ←',
    ins_no_data_hint: 'ابتدا از بخش دانلود، داده دریافت کنید',
    ins_deep_analysis: 'تحلیل عمیق',
    ins_running_analysis: 'در حال اجرای تحلیل…',
    ins_rec_for_next: 'پیشنهاد استراتژی برای دورهٔ بعدی',
    ins_recent_sharpe: 'شارپ اخیر',
    ins_confidence: 'سطح اطمینان',
    ins_regime: 'رژیم', ins_momentum: 'مومنتوم',
    ins_alt_strategy: 'رژیم با این استراتژی همخوانی کامل ندارد — گزینهٔ جایگزین مطابق رژیم: ',
    ins_futures_mode: 'حالت فیوچرز: استراتژی‌ها با هر دو پوزیشن Long و Short تست شده‌اند',
    ins_sharpe_scores: 'امتیاز استراتژی‌ها (۹۰ روز اخیر)',
    ins_rotation_mini: 'چرخش استراتژی (خلاصه)',
    ins_rotation_legend: 'هر ستون = یک پنجره | رنگ = برترین استراتژی | hover جزئیات',
    ins_rotation_price_title: 'چرخش استراتژی روی نمودار قیمت',
    ins_rotation_price_hint: 'رنگ پس‌زمینه = برترین استراتژی آن دوره',
    ins_ml_fitness: 'تناسب ML', ins_ml_fitness_sub: 'مناسب بودن برای یادگیری ماشین',
    ins_rl_fitness: 'تناسب RL', ins_rl_fitness_sub: 'مناسب بودن برای یادگیری تقویتی',
    ins_advanced: 'تحلیل پیشرفته — Oracle در برابر Walk-Forward و Buy&Hold',
    ins_advanced_hint: '(نمودار مقایسه‌ای برای ارزیابی کیفیت پیشنهاد)',
    ins_daily_decision: 'تصمیم روزانه (هر دوره بهترین استراتژی قبلی)',
    ins_oracle_ceiling: 'Oracle — سقف نظری (با دانستن آینده)',
    ins_m_wf_sharpe: 'شارپ تصمیم روزانه', ins_m_wf_cagr: 'CAGR تصمیم روزانه',
    ins_m_wf_dd: 'حداکثر افت تصمیم روزانه', ins_m_bh_sharpe: 'شارپ Buy&Hold',
    ins_m_oracle_sharpe: 'شارپ Oracle (سقف)',
    ins_value: 'ارزش ($)',
    conf_high: 'بالا', conf_medium: 'متوسط', conf_low: 'پایین',
    /* ML/RL detail rows */
    d_autocorr: 'خودهمبستگی', d_hurst: 'نمای هرست', d_ic: 'ضریب اطلاعات',
    d_stationarity: 'ایستایی', d_sample: 'تعداد نمونه',
    d_regime_changes: 'تغییرات رژیم', d_regime_diversity: 'تنوع رژیم',
    d_reward_density: 'چگالی پاداش', d_vol_cluster: 'خوشه‌بندی نوسان',
    d_kurtosis: 'کشیدگی (دم‌های چاق)',

    /* ── lab section ──────────────────────────────────────────────── */
    lab_dataset: 'انتخاب دیتاست',
    lab_dataset_ph: 'انتخاب دیتاست…',
    lab_strategy_ph: 'انتخاب استراتژی…',
    lab_futures_notice: 'فیوچرز: استراتژی‌ها هم Long و هم Short باز می‌کنند',
    lab_strategy_params: 'استراتژی و پارامترها',
    lab_strategy: 'استراتژی',
    lab_no_params: 'این استراتژی پارامتر قابل تنظیم ندارد',
    lab_tunable: 'پارامترهای قابل تنظیم:',
    lab_run: 'اجرای بک‌تست',
    lab_optimizer: 'بهینه‌ساز (Grid Search)',
    lab_optimizer_desc: 'جستجوی بهترین ترکیب پارامترها برای استراتژی انتخابی روی دیتاست فعلی',
    lab_run_optimizer: 'اجرای بهینه‌ساز',
    lab_empty: 'یک دیتاست و استراتژی انتخاب کنید، سپس بک‌تست را اجرا کنید',
    lab_result: 'نتایج بک‌تست',
    lab_equity: 'منحنی سهام', lab_position: 'نمودار پوزیشن',
    lab_opt_results: 'نتایج بهینه‌ساز',
    lab_best_params: 'بهترین پارامترها',
    lab_params_col: 'پارامترها',

    /* ── logs section ─────────────────────────────────────────────── */
    logs_title: 'لاگ‌های سیستم',
    logs_lines: 'تعداد خطوط',
    logs_autoscroll: 'پیمایش خودکار',
    logs_none: 'لاگی یافت نشد.',
    logs_stat_lines: 'خطوط',

    /* ── edges section ────────────────────────────────────────────── */
    edges_title: 'لبه‌های اعتبارسنجی‌شده (Walk-Forward)',
    edges_sub: 'خروجیِ اسکنِ خارج‌از‌نمونه — بات‌های قاعده‌محور (Mickey، Wall_E) فقط همین‌ها را اجرا می‌کنند',
    edges_rescan: 'اجرای اسکن دوباره',
    edges_scanning: 'شروع اسکن…',
    edges_no_report: 'هنوز گزارشی تولید نشده. «اجرای اسکن دوباره» را بزنید.',
    edges_live_tf: 'تایم‌فریمِ زنده',
    edges_scanned: 'ترکیب‌های اسکن‌شده',
    edges_valid: 'لبه‌های معتبر (OOS)',
    edges_alerts: 'هشدارها',
    edges_last_scan: 'آخرین اسکن',
    edges_chart_sharpe: 'شارپ بهترین کاندیداها',
    edges_chart_tf: 'توزیعِ تایم‌فریم‌ها',
    edges_chart_scatter: 'شارپ در برابر بازده (اندازه = تعداد معاملات)',
    edges_scatter_note: 'هر نقطه یک کاندیدِ معتبر است. سبز = بازدهٔ مثبت، قرمز = بازدهٔ منفی.',
    edges_chart_hist: 'روندِ تعداد لبه‌های معتبر',
    edges_hist_note: '{n} اسکنِ ثبت‌شده',
    edges_alerts_title: 'هشدارهای تغییرِ تایم‌فریم',
    edges_no_alert: 'هیچ تایم‌فریمِ بهتری از «{tf}» پیدا نشد — تنظیمِ فعلیِ بات بهینه است.',
    edges_alert_better: '{symbol}: لبهٔ قوی‌تری روی {ctf} پیدا شد (شارپ {csharpe} با {cstrat}) نسبت به تایم‌فریمِ زندهٔ {ltf} (شارپ {lsharpe}). برای فعال‌سازی، بات باید با تایم‌فریم {ctf} ری‌استارت شود — این تغییر دستی/تأییدی است.',
    edges_live_plan: 'پلنِ زندهٔ بات (تایم‌فریم {tf})',
    edges_plan_note: 'بات فقط نمادهایی را معامله می‌کند که هم در whitelist باشند و هم کاندیدِ معتبر داشته باشند.',
    edges_all_candidates: 'همهٔ کاندیداهای معتبر (۲۰ مورد برتر)',
    edges_no_live_candidate: 'کاندیدی روی تایم‌فریم زنده نیست',
    edges_col_symbol: 'نماد', edges_col_rule: 'قاعده', edges_col_dir: 'جهت',
    edges_col_sharpe_oos: 'شارپ (OOS)', edges_col_positive: '٪ مثبت',
    edges_col_return_oos: 'بازده OOS', edges_col_exchange: 'صرافیِ مرجع',
    edges_col_tf: 'TF', edges_col_trades: 'معاملات/پنجره',
    edges_dir_both: 'دوطرفه', edges_dir_long: 'فقط خرید',
    edges_oos_return: 'بازده OOS', edges_strategy: 'استراتژی', edges_trades_split: 'معاملات/پنجره',
    edges_valid_candidates: 'کاندیداهای معتبر',
    edges_valid_of: '{passed} معتبر از {scanned}',

    /* ── regimes ──────────────────────────────────────────────────── */
    regime_trending_up: 'ترند صعودی',
    regime_trending_down: 'ترند نزولی',
    regime_ranging: 'رنجینگ',
    regime_mean_reverting: 'میانگین‌گرا',
    regime_unknown: 'نامشخص',

    /* ── recommendation reason codes (params: {n}, {total}, {regime}, {margin}) */
    reason_window_wins: '{n} از {total} پنجرهٔ اخیر بهترین بود',
    reason_regime_fit: 'رژیم «{regime}» با این استراتژی همخوانی دارد',
    reason_regime_misfit: 'رژیم «{regime}» با این استراتژی همخوانی ضعیف دارد',
    reason_margin_strong: 'فاصلهٔ شارپ {margin} از استراتژی دوم',
    reason_margin_mild: 'شارپ کمی بهتر از رقبا (فاصله {margin})',
    reason_margin_weak: 'فاصلهٔ شارپ با رقبا کم است — بازار در تغییرِ رژیم',

    /* ── ML/RL hint codes ─────────────────────────────────────────── */
    mlrl_ml: 'ML مناسب‌تر است — داده با ثبات (ایستایی={stationarity})، IC={ic}، هرست={hurst}',
    mlrl_ml_bot: 'پیشنهاد: یک مدل ML (مثل GBM یا XGBoost) با فیچرهای تکنیکال روی این جفت‌ارز',
    mlrl_rl: 'RL مناسب‌تر است — تنوع رژیم ({regime_changes} تغییر)، چگالی={density}٪، خوشه‌بندی نوسان={vol}',
    mlrl_rl_bot: 'پیشنهاد: یک بات RL (مثل PPO یا SAC) برای یادگیری سوییچِ رژیم روی این جفت‌ارز',
    mlrl_both: 'هر دو رویکرد ML و RL قابل استفاده هستند (ML={ml}، RL={rl})',
    mlrl_both_bot: 'می‌توانید هر دو رویکرد را آزمایش کنید',
    mlrl_insufficient: 'دادهٔ کافی برای ارزیابی وجود ندارد',

    /* ── job message codes ────────────────────────────────────────── */
    job_dl_start: 'شروع دانلود…',
    job_dl_tf: 'دانلود {symbol} {tf} ({market}) از {exchange}…',
    job_dl_done: 'دانلود {symbol} کامل شد ({n} تایم‌فریم)',
    job_res_start: 'شروع بک‌تست…',
    job_res_bt: 'بک‌تست {strategy} روی {symbol} {tf}{short}…',
    job_res_done: 'ریسرچ کامل شد — {datasets} دیتاست، {strategies} استراتژی',
    job_opt_start: 'شروع بهینه‌سازی…',
    job_opt_combo: 'ترکیب {i}/{total}: {params}',
    job_opt_done: 'بهینه‌سازی کامل شد — {n} ترکیب، بهترین شارپ: {sharpe}',
    job_edge_start: 'اسکنِ walk-forward شروع شد…',
    job_edge_error: 'خطا در اسکن',
    job_edge_done: 'اسکن کامل شد — {passed} لبهٔ معتبر، {alerts} هشدار',
    job_error: 'خطا: {error}',
  },

  en: {
    /* ── brand / chrome ───────────────────────────────────────────── */
    brand: 'QuantResearch',
    brand_tagline: 'Quant Research Platform',
    version_label: 'v1.2',
    theme_aurora: 'Midnight Aurora',

    /* ── navigation ───────────────────────────────────────────────── */
    nav_download: 'Download Data',
    nav_inventory: 'Data Inventory',
    nav_research: 'Research',
    nav_report: 'Report',
    nav_insights: 'Insights',
    nav_lab: 'Lab',
    nav_edges: 'Edges',
    nav_logs: 'Logs',

    /* ── section titles + subtitles ───────────────────────────────── */
    title_download: 'Download Data', sub_download: 'Fetch market data from exchanges',
    title_inventory: 'Data Inventory', sub_inventory: 'Datasets available on the system',
    title_research: 'Research', sub_research: 'Run strategy backtests',
    title_report: 'Report', sub_report: 'Quant analysis results',
    title_insights: 'Insights', sub_insights: 'Best-strategy recommendation',
    title_lab: 'Lab', sub_lab: 'Customize & optimize strategies',
    title_edges: 'Validated Edges', sub_edges: 'Walk-forward validated edges',
    title_logs: 'System Logs', sub_logs: 'Internal platform events',

    /* ── common ───────────────────────────────────────────────────── */
    refresh: 'Refresh', reload: 'Reload', back: 'Back', run: 'Run',
    loading: 'Loading…', error: 'Error', error_colon: 'Error: ',
    no_data: 'No data found', insufficient_data: 'Not enough data',
    candles: 'candles', delete_file: 'Delete file', search: 'Search…',
    all_exchanges: 'All exchanges', all_levels: 'All levels',
    select_placeholder: 'Select…', progress: 'Progress',
    benchmark: 'benchmark', zero: 'Zero', average: 'Mean', normal_dist: 'Normal distribution',

    /* ── download section ─────────────────────────────────────────── */
    dl_settings: 'Download Settings',
    dl_exchange: 'Exchange',
    dl_symbol: 'Pair / Symbol',
    dl_symbol_ph: 'e.g. BTCUSDT',
    dl_symbol_select_ph: 'Select symbol…',
    dl_symbol_toggle: 'Toggle list / manual',
    dl_loading_symbols: 'Loading symbols…',
    dl_range: 'Date range',
    dl_from: 'From', dl_to: 'To',
    dl_market: 'Market type',
    dl_market_spot: 'Spot', dl_market_futures: 'Futures / Perp',
    dl_timeframes: 'Timeframes',
    dl_start_btn: 'Start Download',
    dl_downloading: 'Downloading…',
    dl_history: 'Download History',
    dl_history_empty: 'No downloads yet',
    dl_fill_all: 'Please fill in all fields',

    /* ── inventory section ────────────────────────────────────────── */
    inv_summary: 'Available Data Summary',
    inv_files: 'Parquet Files',
    inv_metric_files: 'Files', inv_metric_candles: 'Candles',
    inv_metric_exchanges: 'Exchanges', inv_metric_symbols: 'Symbols',
    inv_metric_disk: 'Disk size',
    inv_confirm_delete: 'Delete "{file}"?\nThis action cannot be undone.',
    inv_delete_failed: 'Delete failed: ',

    /* ── research section ─────────────────────────────────────────── */
    res_select_data: 'Select Data',
    res_datasets_label: 'Datasets (multi-select)',
    res_selected_count: '{n} dataset(s) selected',
    res_date_filter: 'Date range filter (optional)',
    res_bt_settings: 'Backtest Settings',
    res_capital: 'Initial capital ($)',
    res_return_type: 'Return type',
    res_simple: 'Simple', res_log: 'Log',
    res_fee: 'Fee (bps)', res_slippage: 'Slippage (bps)',
    res_strategies: 'Strategies',
    res_run_btn: 'Run Research',
    res_running: 'Running…',
    res_need_dataset: 'Select at least one dataset',
    res_need_strategy: 'Select at least one strategy',

    /* ── report section ───────────────────────────────────────────── */
    rep_empty_title: 'Run a research job first',
    rep_empty_sub: 'Go to the Research section and run a backtest',
    rep_select_dataset: 'Select a dataset to display',
    rep_tab_equity: 'Equity', rep_tab_drawdown: 'Drawdown',
    rep_tab_monthly: 'Monthly Returns', rep_tab_rolling: 'Rolling Sharpe',
    rep_tab_distribution: 'Return Distribution', rep_tab_metrics: 'Metrics Table',
    rep_equity_curve: 'Equity Curve',
    rep_show_regime: 'Show regime',
    rep_drawdown: 'Drawdown (from peak)',
    rep_monthly: 'Monthly Returns (Heatmap)',
    rep_rolling: 'Rolling Sharpe (30 bars)',
    rep_distribution: 'Return Distribution',
    rep_metrics_full: 'Full Metrics Table',
    rep_portfolio_value: 'Portfolio value ($)',
    rep_count: 'Count', rep_count_times: 'times',
    rep_metric: 'Metric',
    m_total_return: 'Total Return', m_cagr: 'CAGR', m_sharpe: 'Sharpe',
    m_sortino: 'Sortino', m_calmar: 'Calmar', m_max_dd: 'Max Drawdown',
    m_profit_factor: 'Profit Factor', m_win_rate: 'Win Rate',
    stat_mean: 'Mean', stat_std: 'Std Dev',
    stat_skew: 'Skewness', stat_kurt: 'Kurtosis',

    /* ── insights section ─────────────────────────────────────────── */
    ins_select_dataset: 'Select a dataset for deep analysis',
    ins_intro: 'Pick a dataset to see a full strategy breakdown, regime rotation, and the oracle equity curve.',
    ins_loading_datasets: 'Loading datasets…',
    ins_click_to_analyze: 'Click for deep analysis →',
    ins_no_data_hint: 'Download data from the Download section first',
    ins_deep_analysis: 'Deep Analysis',
    ins_running_analysis: 'Running analysis…',
    ins_rec_for_next: 'Recommended strategy for the next period',
    ins_recent_sharpe: 'Recent Sharpe',
    ins_confidence: 'Confidence',
    ins_regime: 'Regime', ins_momentum: 'Momentum',
    ins_alt_strategy: 'Regime is not a perfect fit for this strategy — regime-aligned alternative: ',
    ins_futures_mode: 'Futures mode: strategies were tested with both Long and Short positions',
    ins_sharpe_scores: 'Strategy Scores (last 90 days)',
    ins_rotation_mini: 'Strategy Rotation (summary)',
    ins_rotation_legend: 'Each column = one window | color = top strategy | hover for details',
    ins_rotation_price_title: 'Strategy Rotation on Price Chart',
    ins_rotation_price_hint: 'Background color = best strategy for that period',
    ins_ml_fitness: 'ML Fitness', ins_ml_fitness_sub: 'Suitability for Machine Learning',
    ins_rl_fitness: 'RL Fitness', ins_rl_fitness_sub: 'Suitability for Reinforcement Learning',
    ins_advanced: 'Advanced — Oracle vs Walk-Forward vs Buy&Hold',
    ins_advanced_hint: '(comparison chart to gauge recommendation quality)',
    ins_daily_decision: 'Daily decision (each period uses the previously best strategy)',
    ins_oracle_ceiling: 'Oracle — theoretical ceiling (with future knowledge)',
    ins_m_wf_sharpe: 'Daily-decision Sharpe', ins_m_wf_cagr: 'Daily-decision CAGR',
    ins_m_wf_dd: 'Daily-decision MaxDD', ins_m_bh_sharpe: 'Buy&Hold Sharpe',
    ins_m_oracle_sharpe: 'Oracle Sharpe (ceiling)',
    ins_value: 'Value ($)',
    conf_high: 'High', conf_medium: 'Medium', conf_low: 'Low',
    d_autocorr: 'Autocorrelation', d_hurst: 'Hurst Exponent', d_ic: 'Info Coefficient',
    d_stationarity: 'Stationarity', d_sample: 'Sample Count',
    d_regime_changes: 'Regime Changes', d_regime_diversity: 'Regime Diversity',
    d_reward_density: 'Reward Density', d_vol_cluster: 'Vol. Clustering',
    d_kurtosis: 'Kurtosis (Fat Tails)',

    /* ── lab section ──────────────────────────────────────────────── */
    lab_dataset: 'Select Dataset',
    lab_dataset_ph: 'Select dataset…',
    lab_strategy_ph: 'Select strategy…',
    lab_futures_notice: 'Futures: strategies open both Long and Short positions',
    lab_strategy_params: 'Strategy & Parameters',
    lab_strategy: 'Strategy',
    lab_no_params: 'This strategy has no tunable parameters',
    lab_tunable: 'Tunable parameters:',
    lab_run: 'Run Backtest',
    lab_optimizer: 'Optimizer (Grid Search)',
    lab_optimizer_desc: 'Search the best parameter combination for the selected strategy on the current dataset',
    lab_run_optimizer: 'Run Optimizer',
    lab_empty: 'Select a dataset and a strategy, then run the backtest',
    lab_result: 'Backtest Results',
    lab_equity: 'Equity Curve', lab_position: 'Position Chart',
    lab_opt_results: 'Optimizer Results',
    lab_best_params: 'Best Parameters',
    lab_params_col: 'Parameters',

    /* ── logs section ─────────────────────────────────────────────── */
    logs_title: 'System Logs',
    logs_lines: 'Number of lines',
    logs_autoscroll: 'auto-scroll',
    logs_none: 'No logs found.',
    logs_stat_lines: 'Lines',

    /* ── edges section ────────────────────────────────────────────── */
    edges_title: 'Validated Edges (Walk-Forward)',
    edges_sub: 'Out-of-sample scan output — rule-based bots (Mickey, Wall_E) only trade these',
    edges_rescan: 'Re-run Scan',
    edges_scanning: 'Starting scan…',
    edges_no_report: 'No report generated yet. Click "Re-run Scan".',
    edges_live_tf: 'Live timeframe',
    edges_scanned: 'Combos scanned',
    edges_valid: 'Valid edges (OOS)',
    edges_alerts: 'Alerts',
    edges_last_scan: 'Last scan',
    edges_chart_sharpe: 'Sharpe of Top Candidates',
    edges_chart_tf: 'Timeframe Distribution',
    edges_chart_scatter: 'Sharpe vs Return (size = trade count)',
    edges_scatter_note: 'Each point is a valid candidate. Green = positive return, red = negative return.',
    edges_chart_hist: 'Trend of Valid Edge Count',
    edges_hist_note: '{n} scans recorded',
    edges_alerts_title: 'Timeframe-change Alerts',
    edges_no_alert: 'No timeframe better than "{tf}" was found — the bot\'s current setting is optimal.',
    edges_alert_better: '{symbol}: a stronger edge was found on {ctf} (Sharpe {csharpe} with {cstrat}) vs the live timeframe {ltf} (Sharpe {lsharpe}). To activate, the bot must restart on timeframe {ctf} — this is a manual/approved change.',
    edges_live_plan: 'Live Bot Plan (timeframe {tf})',
    edges_plan_note: 'The bot only trades symbols that are both whitelisted and have a valid candidate.',
    edges_all_candidates: 'All Valid Candidates (top 20)',
    edges_no_live_candidate: 'No candidate on the live timeframe',
    edges_col_symbol: 'Symbol', edges_col_rule: 'Rule', edges_col_dir: 'Direction',
    edges_col_sharpe_oos: 'Sharpe (OOS)', edges_col_positive: '% positive',
    edges_col_return_oos: 'OOS return', edges_col_exchange: 'Ref. exchange',
    edges_col_tf: 'TF', edges_col_trades: 'Trades/window',
    edges_dir_both: 'Both', edges_dir_long: 'Long only',
    edges_oos_return: 'OOS return', edges_strategy: 'Strategy', edges_trades_split: 'Trades/window',
    edges_valid_candidates: 'Valid candidates',
    edges_valid_of: '{passed} valid of {scanned}',

    /* ── regimes ──────────────────────────────────────────────────── */
    regime_trending_up: 'Trending Up',
    regime_trending_down: 'Trending Down',
    regime_ranging: 'Ranging',
    regime_mean_reverting: 'Mean-Reverting',
    regime_unknown: 'Unknown',

    /* ── recommendation reason codes ──────────────────────────────── */
    reason_window_wins: 'Best in {n} of the last {total} windows',
    reason_regime_fit: 'Regime "{regime}" fits this strategy',
    reason_regime_misfit: 'Regime "{regime}" is a weak fit for this strategy',
    reason_margin_strong: 'Sharpe lead of {margin} over the runner-up',
    reason_margin_mild: 'Slightly better Sharpe than peers (lead {margin})',
    reason_margin_weak: 'Sharpe lead over peers is small — market is changing regime',

    /* ── ML/RL hint codes ─────────────────────────────────────────── */
    mlrl_ml: 'ML is a better fit — stable data (stationarity={stationarity}), IC={ic}, Hurst={hurst}',
    mlrl_ml_bot: 'Suggestion: an ML model (e.g. GBM or XGBoost) with technical features on this pair',
    mlrl_rl: 'RL is a better fit — regime diversity ({regime_changes} changes), density={density}%, vol-clustering={vol}',
    mlrl_rl_bot: 'Suggestion: an RL bot (e.g. PPO or SAC) to learn regime switching on this pair',
    mlrl_both: 'Both ML and RL are usable (ML={ml}, RL={rl})',
    mlrl_both_bot: 'You can experiment with both approaches',
    mlrl_insufficient: 'Not enough data to assess',

    /* ── job message codes ────────────────────────────────────────── */
    job_dl_start: 'Starting download…',
    job_dl_tf: 'Downloading {symbol} {tf} ({market}) from {exchange}…',
    job_dl_done: 'Download of {symbol} complete ({n} timeframes)',
    job_res_start: 'Starting backtest…',
    job_res_bt: 'Backtesting {strategy} on {symbol} {tf}{short}…',
    job_res_done: 'Research complete — {datasets} datasets, {strategies} strategies',
    job_opt_start: 'Starting optimization…',
    job_opt_combo: 'Combo {i}/{total}: {params}',
    job_opt_done: 'Optimization complete — {n} combos, best Sharpe: {sharpe}',
    job_edge_start: 'Walk-forward scan started…',
    job_edge_error: 'Scan failed',
    job_edge_done: 'Scan complete — {passed} valid edges, {alerts} alerts',
    job_error: 'Error: {error}',
  },
};

/* Strategy display names + descriptions (descriptions are localized). */
const STRATEGY_LABELS = {
  ema_trend: 'EMA Trend', rsi_mean_reversion: 'RSI Mean Rev.',
  bollinger_mean_reversion: 'Bollinger', donchian_breakout: 'Donchian',
  atr_breakout: 'ATR Breakout', macd_cross: 'MACD Cross',
  stochastic_mr: 'Stochastic MR', ichimoku: 'Ichimoku Cloud',
  supertrend: 'SuperTrend', vwap_deviation: 'VWAP Dev.',
  cmf_trend: 'CMF Trend', hammer_pattern: 'Hammer',
  engulfing: 'Engulfing', ml_signal: 'ML Signal (GBM)',
};

const STRATEGY_DESC = {
  fa: {
    ema_trend: 'EMA20 از بالا از EMA100 بگذرد → Long',
    rsi_mean_reversion: 'ورود RSI<30، خروج RSI>50',
    bollinger_mean_reversion: 'ورود زیر باند پایین (z<-2)، خروج نزدیک میانگین',
    donchian_breakout: 'شکست بالای سقف ۵۵ روزه → Long',
    atr_breakout: 'بسته شدن بالای MA + 1.5×ATR → Long',
    macd_cross: 'عبور خط MACD از خط سیگنال → Long',
    stochastic_mr: '%D<20 → Long، %D>80 → خروج',
    ichimoku: 'Long بالای ابر، Short زیر ابر + Tenkan/Kijun',
    supertrend: 'ترند مبتنی بر ATR: Long بالای خط، Short زیر خط',
    vwap_deviation: 'ورود هنگام انحراف قیمت از VWAP — مناسب کریپتو',
    cmf_trend: 'Chaikin Money Flow — Long جریان مثبت، Short جریان منفی',
    hammer_pattern: 'Hammer → Long | Shooting Star → Short (فیوچرز)',
    engulfing: 'کندل بلعندهٔ صعودی/نزولی — الگوی ژاپنی قوی',
    ml_signal: 'Gradient Boosting روی RSI، MACD، Bollinger، ATR — آموزش روی ۶۵٪ اول',
  },
  en: {
    ema_trend: 'EMA20 crosses above EMA100 → Long',
    rsi_mean_reversion: 'Enter RSI<30, exit RSI>50',
    bollinger_mean_reversion: 'Enter below lower band (z<-2), exit near the mean',
    donchian_breakout: 'Break above the 55-bar high → Long',
    atr_breakout: 'Close above MA + 1.5×ATR → Long',
    macd_cross: 'MACD line crosses the signal line → Long',
    stochastic_mr: '%D<20 → Long, %D>80 → exit',
    ichimoku: 'Long above the cloud, Short below + Tenkan/Kijun',
    supertrend: 'ATR-based trend: Long above the line, Short below',
    vwap_deviation: 'Enter on price deviation from VWAP — crypto-friendly',
    cmf_trend: 'Chaikin Money Flow — Long on positive flow, Short on negative',
    hammer_pattern: 'Hammer → Long | Shooting Star → Short (futures)',
    engulfing: 'Bullish/bearish engulfing — a strong Japanese pattern',
    ml_signal: 'Gradient Boosting on RSI, MACD, Bollinger, ATR — trained on the first 65%',
  },
};

const STRATEGY_TAGS = {
  ema_trend: 'Trend', rsi_mean_reversion: 'MR', bollinger_mean_reversion: 'MR',
  donchian_breakout: 'Trend', atr_breakout: 'Trend', macd_cross: 'Trend',
  stochastic_mr: 'MR', ichimoku: 'Trend 🇯🇵', supertrend: 'Trend',
  vwap_deviation: 'MR 🔷', cmf_trend: 'Trend', hammer_pattern: 'MR 🕯️',
  engulfing: 'MR 🕯️', ml_signal: 'ML',
};

const MONTHS = {
  fa: ['ژانویه','فوریه','مارس','آوریل','مه','ژوئن','ژوئیه','اوت','سپتامبر','اکتبر','نوامبر','دسامبر'],
  en: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
};

/* ── runtime ───────────────────────────────────────────────────────── */
let LANG = 'fa';

function t(key, params) {
  const dict = I18N[LANG] || I18N.fa;
  let s = dict[key];
  if (s === undefined) s = (I18N.fa[key] !== undefined ? I18N.fa[key] : key);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), v);
    }
  }
  return s;
}

function strategyLabel(name) { return STRATEGY_LABELS[name] || name; }
function strategyDesc(name) { return (STRATEGY_DESC[LANG] || STRATEGY_DESC.fa)[name] || ''; }
function regimeLabel(code) { return t('regime_' + (code || 'unknown')); }
function months() { return MONTHS[LANG] || MONTHS.fa; }

/* Resolve a backend recommendation reason {code, ...params} to localized text.
   A `regime` param is itself a code, so localize it before interpolation. */
function recReason(r) {
  if (typeof r === 'string') return r;            // legacy fallback
  if (!r || !r.code) return '';
  const params = { ...r };
  if (params.regime) params.regime = regimeLabel(params.regime);
  return t(r.code, params);
}

/* Resolve the ML/RL fitness hint/bot-hint from structured payload. */
function mlrlHint(fit) {
  if (!fit) return { hint: '', bot: '' };
  if (fit.hint_code) {
    return { hint: t(fit.hint_code, fit.hint_params || {}),
             bot: t(fit.bot_hint_code, fit.hint_params || {}) };
  }
  return { hint: fit.hint || '', bot: fit.bot_hint || '' };  // legacy fallback
}

/* Resolve a job's message: prefer language-neutral code, fall back to text. */
function jobMessage(job) {
  if (!job) return '';
  if (job.message_code) return t(job.message_code, job.message_params || {});
  return job.message || '';
}

/* Apply translations to all tagged elements under `root` (default document). */
function applyI18n(root) {
  root = root || document;
  root.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  root.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.getAttribute('data-i18n-html'));
  });
  root.querySelectorAll('[data-i18n-ph]').forEach(el => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-ph')));
  });
  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
  });
}

function setLang(lang) {
  LANG = (lang === 'en') ? 'en' : 'fa';
  try { localStorage.setItem('qr_lang', LANG); } catch (e) {}
  const html = document.documentElement;
  html.lang = LANG;
  html.dir = LANG === 'fa' ? 'rtl' : 'ltr';
  document.querySelectorAll('.lang-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.lang === LANG);
  });
  applyI18n();
  if (typeof window.onLangChange === 'function') window.onLangChange();
}
