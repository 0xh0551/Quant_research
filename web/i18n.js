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
    version_label: 'نسخهٔ ۱.۳',
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
    res_exec_style: 'مدل اجرا', res_exec_taker: 'تیکر (سریع)', res_exec_maker: 'میکر (شبیه‌ساز سفارش)',
    res_real_funding: 'فاندینگ واقعی (تاریخچهٔ ذخیره‌شده، فقط فیوچرز)',
    res_exec_hint: 'میکر: فیل فقط با عبور قیمت از لیمیت + صبر/فال‌بک تیکر + فیل جزئی با سقف مشارکت حجم',
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
    m_exec_fill_ratio: 'نسبت فیل', m_exec_maker_rate: 'فیل میکر',
    m_exec_fallback: 'فال‌بک تیکر', m_exec_missed: 'معاملات ازدست‌رفته', m_exec_cost: 'هزینهٔ مؤثر (bps)',
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
    edges_sub: 'خروجیِ اسکنِ خارج‌از‌نمونه — بات‌های قاعده‌محور (بریج) فقط همین‌ها را اجرا می‌کنند',
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
    edges_col_status: 'وضعیت',
    edges_deploy_deployable: 'قابل‌استقرار', edges_deploy_robust: 'مستحکم', edges_deploy_passed: 'فقط معتبر',
    edges_deploy_legend: '🟢 قابل‌استقرار = به بات بریج منتقل می‌شود (مستحکم + استراتژیِ پشتیبانی‌شدهٔ بریج). 🔵 مستحکم = از گیتِ چندصرافی/DSR رد شده ولی بریج پیاده‌اش نکرده. ⚪ فقط معتبر = فقط گیتِ شُلِ OOS را رد کرده (اغلب کم‌نقدینگی/اورفیت). توجه: بات‌های RL/ML از این لبه‌ها تغذیه نمی‌شوند؛ آن‌ها جفت‌ها را از امتیاز RL/ML می‌گیرند.',
    edges_col_tf: 'TF', edges_col_trades: 'معاملات/پنجره',
    edges_dir_both: 'دوطرفه', edges_dir_long: 'فقط خرید',
    edges_oos_return: 'بازده OOS', edges_strategy: 'استراتژی', edges_trades_split: 'معاملات/پنجره',
    edges_valid_candidates: 'کاندیداهای معتبر',
    edges_valid_of: '{passed} معتبر از {scanned}',

    /* ── new navigation + sections (Tiers 0-4) ────────────────────── */
    nav_crossex: 'بین‌صرافی', nav_portfolio: 'پرتفوی', nav_models: 'مدل‌ها', nav_quality: 'کیفیت داده',
    title_crossex: 'تحلیل بین‌صرافی', sub_crossex: 'لبه‌های بین صرافی‌ها — lead-lag، هم‌انباشتگی، بیسیس',
    title_portfolio: 'ساخت پرتفوی', sub_portfolio: 'وزن‌دهی و سایزینگ آگاه از همبستگی',
    title_models: 'مدل‌ها (ML/RL)', sub_models: 'ارزیابی واقعی ML با CV پاک‌سازی‌شده + پیشنهاد RL',
    title_quality: 'کیفیت داده و فوروارد-تست', sub_quality: 'سلامت داده + مقایسهٔ انتظار با تحقق',
    analyze: 'تحلیل', build: 'ساخت', evaluate: 'ارزیابی', optimize: 'بهینه‌سازی',
    timeframe: 'تایم‌فریم', symbol_label: 'نماد', running: 'در حال اجرا…',

    /* ── fleet risk ───────────────────────────────────────────────── */
    nav_fleet: 'ریسک ناوگان',
    title_fleet: 'ریسک تجمیعی ناوگان', sub_fleet: 'اکسپوژر، لوریج و هم‌جهتی همهٔ بات‌ها در یک نگاه',
    fleet_title: 'ریسک تجمیعی ناوگان',
    fleet_sub_note: 'جمع پوزیشن‌های باز همهٔ بات‌ها: دلتای خالص بتا-محور، لوریج ناخالص، تمرکز و همبستگی — چیزی که هیچ بات تکی نمی‌بیند.',
    fleet_refresh_live: 'اسنپ‌شات زنده',
    fleet_metrics: 'شاخص‌های ناوگان',
    fleet_exposure_chart: 'اکسپوژر خالص هر دارایی (β-وزنی)',
    fleet_corr_chart: 'همبستگی دارایی‌های باز (۳۰ روز)',
    fleet_per_bot: 'وضعیت هر بات',
    fleet_positions: 'پوزیشن‌های باز (کل ناوگان)',
    fleet_m_equity: 'اکوییتی ناوگان', fleet_m_gross: 'ناخالص نوشنال', fleet_m_net: 'خالص نوشنال',
    fleet_m_lev: 'لوریج ناخالص', fleet_m_delta: 'دلتای خالص β', fleet_m_hhi: 'تمرکز (HHI)',
    fleet_m_npos: 'پوزیشن باز', fleet_m_corr: 'میانگین همبستگی',
    fleet_h_bot: 'بات', fleet_h_equity: 'اکوییتی', fleet_h_realized: 'PnL تحقق‌یافته',
    fleet_h_upnl: 'PnL باز', fleet_h_gross: 'نوشنال', fleet_h_lev: 'لوریج', fleet_h_open: 'باز',
    fleet_h_pair: 'جفت', fleet_h_side: 'جهت', fleet_h_stake: 'استیک', fleet_h_notional: 'نوشنال',
    fleet_h_mark: 'قیمت مارک', fleet_h_age: 'تازگی قیمت', fleet_h_beta: 'β به BTC',
    fleet_stale: 'کهنه',
    fleet_ok: 'هیچ حد ریسکی نقض نشده — ناوگان داخل محدوده است.',
    fleet_alert_gross_leverage: 'لوریج ناخالص ناوگان ({value}x) از سقف {limit}x عبور کرده',
    fleet_alert_net_delta: 'دلتای خالص β ناوگان ({value}٪ اکوییتی) از حد {limit}٪ عبور کرده',
    fleet_alert_asset_concentration: 'تمرکز روی {context}: {value}٪ از ناخالص (حد {limit}٪)',
    fleet_alert_bot_leverage: 'لوریج بات {context} برابر {value}x است (حد {limit}x)',
    fleet_alert_bot_db_missing: 'دیتابیس بات {context} در دسترس نیست',
    fleet_alert_crowding_corr: 'میانگین همبستگی دارایی‌های باز {value} است (حد {limit}) — ریسک هم‌جهتی',
    fleet_empty: 'هیچ پوزیشن بازی در ناوگان نیست یا local.json پیکربندی نشده است.',

    /* ── alt-data ─────────────────────────────────────────────────── */
    nav_altdata: 'آلت-دیتا',
    title_altdata: 'آلت-دیتا', sub_altdata: 'پوزیشنینگ، وُل ضمنی (DVOL)، ساختار زمانی بیسیس، لیکوییدیشن',
    alt_title: 'آلت-دیتا: پوزیشنینگ، وُل ضمنی، بیسیس، لیکوییدیشن',
    alt_sub_note: 'رژیم تا امروز فقط از دادهٔ تحقق‌یافته تغذیه می‌شد؛ این‌ها حالت آینده‌نگر بازارند: وُلِ قیمت‌گذاری‌شده، کجی جمعیت، کری، و جریان اجباری.',
    alt_refresh: 'دریافت زنده',
    alt_metrics: 'وضعیت فعلی',
    alt_dvol_chart: 'DVOL بیت‌کوین (وُل ضمنی ۳۰ روزه)',
    alt_ls_chart: 'نسبت لانگ/شورت حساب‌ها (BTC)',
    alt_term_chart: 'ساختار زمانی بیسیس (سالانه ٪)',
    alt_extremes: 'فاندینگ‌های افراطی صرافی',
    alt_liq: 'تیپ لیکوییدیشن (OKX BTC)',
    alt_m_ls: 'L/S حساب‌ها (BTC)', alt_m_taker: 'نسبت تیکر (BTC)',
    alt_m_liq24: 'لیکوییدیشن ۲۴h', alt_m_perp_basis: 'کری پرپ (سالانه)',
    alt_h_funding_ann: 'فاندینگ سالانه', alt_h_premium: 'پرمیوم (bps)',
    alt_h_time: 'زمان', alt_h_side: 'سمت', alt_h_notional: 'نوشنال',
    alt_shorts_liq: 'شورت‌ها لیکویید', alt_longs_liq: 'لانگ‌ها لیکویید',
    alt_no_hints: 'هیچ سیگنال رژیم افراطی‌ای در آلت-دیتا نیست.',
    alt_hint_dvol_high: 'DVOL در دهک بالای تاریخچهٔ اخیر است — وُل ضمنی کشیده؛ سایز و لوریج را محتاط کنید.',
    alt_hint_dvol_low: 'DVOL در دهک پایین تاریخچهٔ اخیر است — وُل ارزان و بازار آرام؛ ریسک شکستِ ناگهانی رژیم.',
    alt_hint_crowd_long: 'جمعیت به‌شدت لانگ است (L/S ≥ 3) — ریسک لیکوییدیشن آبشاری در ریزش.',
    alt_hint_crowd_short: 'جمعیت به‌شدت شورت است (L/S ≤ 0.7) — ریسک شورت‌اسکوییز.',
    alt_hint_backwardation: 'ساختار زمانی در بک‌واردیشن است — فشار فروش/استرس در بازار مشتقه.',

    /* ── pipeline health ──────────────────────────────────────────── */
    nav_pipeline: 'سلامت پایپ‌لاین',
    title_pipeline: 'ضربان پایپ‌لاین', sub_pipeline: 'هر جاب زمان‌بندی‌شده باید ردی تازه بگذارد — این‌جا همه یک‌جا بازرسی می‌شوند',
    pipe_title: 'ضربان پایپ‌لاین',
    pipe_sub_note: 'کرانتب پاک‌شده، واچر مرده یا دیسک پر، بی‌صدا جاب شبانه را می‌کشد. این‌جا تازگیِ خروجیِ هر جاب ثبت‌شده ممیزی می‌شود؛ جاب بحرانیِ عقب‌افتاده = آلارم.',
    pipe_audit: 'بازرسی',
    pipe_jobs: 'وضعیت جاب‌ها',
    pipe_history: 'تاریخچهٔ سلامت (هر بازرسی)',
    pipe_history_empty: 'هنوز تاریخچه‌ای نیست — هر اجرای ممیزی یک نقطه اضافه می‌کند.',
    pipe_all_ok: 'هر {n} جاب خروجی تازه دارند — پایپ‌لاین سالم است.',
    pipe_failing: '{late} جاب عقب‌افتاده و {missing} جاب بدون خروجی',
    pipe_s_ok: 'تازه', pipe_s_late: 'عقب‌افتاده', pipe_s_missing: 'غایب',
    pipe_age: 'عمر',

    /* ── attribution ──────────────────────────────────────────────── */
    nav_attribution: 'اتریبیوشن',
    title_attribution: 'تجزیهٔ PnL', sub_attribution: 'هر دلار سود/ضرر: آلفای تصمیم، اسلیپیج، کارمزد، فاندینگ، MFE-Capture',
    attr_title: 'تجزیهٔ PnL — هر دلار کجا رفت؟',
    attr_sub_note: 'هر ترید بسته به پنج جزء تفکیک می‌شود: آلفایی که استراتژی تصمیم گرفت، آنچه اسلیپیج ورود/خروج پس داد، آنچه کارمزد برداشت، فاندینگ، و باقی‌مانده. جداکنندهٔ «زوال آلفا» از «زوال اجرا».',
    attr_recalc: 'محاسبه',
    attr_totals: 'جمع ناوگان',
    attr_waterfall: 'آبشار PnL',
    attr_capture_chart: 'میانگین MFE-Capture هر بات',
    attr_bot_table: 'تفکیک بات‌ها',
    attr_reason_table: 'تفکیک دلیل خروج (بات انتخاب‌شده)',
    attr_fleet: 'کل ناوگان',
    attr_m_intended: 'آلفای تصمیم', attr_m_slip: 'اسلیپیج', attr_m_fees: 'کارمزد',
    attr_m_funding: 'فاندینگ', attr_m_net: 'خالص', attr_m_residual: 'باقی‌مانده',
    attr_w_entry_slip: 'اسلیپیج ورود', attr_w_exit_slip: 'اسلیپیج خروج',
    attr_h_trades: 'ترید', attr_h_reason: 'دلیل خروج',

    /* ── trial ledger ─────────────────────────────────────────────── */
    nav_trials: 'دفتر آزمون‌ها',
    title_trials: 'دفتر آزمون‌ها', sub_trials: 'حساب تجمعی چندآزمونی — DSR در برابر همهٔ فرضیه‌هایی که تا امروز آزموده‌ایم',
    trials_title: 'دفتر آزمون‌ها (گورستان لبه‌ها)',
    trials_sub_note: 'اسکن شبانه فقط آزمون‌های همان شب را در deflation می‌شمارد؛ اما سوگیری انتخاب در طول شب‌ها انباشته می‌شود. این دفتر هر فرضیهٔ یکتا را یک‌بار ثبت می‌کند و DSR واقعی را در برابر کل تاریخ جست‌وجو محاسبه می‌کند.',
    trials_metrics: 'حساب تجمعی',
    trials_timeline: 'فرضیه‌های یکتای تجمعی در طول زمان',
    trials_strategies: 'تفکیک استراتژی‌ها',
    trials_top: 'لبه‌های برتر: DSR شبانه در برابر DSR تجمعی',
    trials_empty: 'دفترچه هنوز خالی است — با نخستین اسکن شبانهٔ بعدی، همهٔ فرضیه‌های آزموده‌شده در آن ثبت می‌شوند.',
    trials_empty_short: 'هنوز داده‌ای ثبت نشده — منتظر نخستین اسکن.',
    trials_m_unique: 'فرضیهٔ یکتا', trials_m_runs: 'کل اجراها', trials_m_tonight: 'اسکن اخیر',
    trials_m_passed: 'حداقل یک‌بار pass', trials_m_srvar: 'واریانس شارپ',
    trials_cumulative: 'تجمعی', trials_new: 'جدید در روز',
    trials_h_hyps: 'فرضیه', trials_h_passed: 'pass شده', trials_h_passrate: 'نرخ pass',
    trials_h_bestsr: 'بهترین SR/بار',
    trials_h_dsr_night: 'DSR شبانه', trials_h_dsr_cum: 'DSR تجمعی', trials_h_verdict: 'حکم',
    trials_demoted: 'با شمار تجمعی رد می‌شود', trials_survives: 'از deflation تجمعی جان به در برد',

    /* ── stress ───────────────────────────────────────────────────── */
    nav_stress: 'استرس‌تست',
    title_stress: 'استرس‌تست پرتفوی', sub_stress: 'بازپخش رویدادهای دنباله + شوک‌های پارامتریک روی بوک زنده',
    stress_title: 'استرس‌تست پرتفوی زنده',
    stress_sub_note: 'هر سناریو روی پوزیشن‌های باز فعلی ناوگان اجرا می‌شود: حرکت β-مقیاس هر دارایی، لیکوییدیشن ایزوله، فاندینگ همزمان و هزینهٔ فلت‌کردن در بوکِ تحت فشار.',
    stress_run: 'اجرای سناریوها',
    stress_summary: 'خلاصه',
    stress_chart: 'ضربه به اکوییتی در هر سناریو (٪)',
    stress_path_chart: 'مسیر BTC در سناریوی تاریخی',
    stress_table: 'جزئیات سناریوها',
    stress_empty: 'پوزیشن بازی برای استرس وجود ندارد.',
    stress_fallback: 'دادهٔ محلی این پنجره را ندارد — از حرکت مستندشدهٔ تاریخی استفاده شد',
    stress_m_equity: 'اکوییتی', stress_m_positions: 'پوزیشن باز', stress_m_worst: 'بدترین سناریو',
    stress_m_worst_pnl: 'ضرر بدترین سناریو', stress_m_liq: 'حداکثر لیکوییدیشن',
    stress_h_scenario: 'سناریو', stress_h_move: 'حرکت بازار', stress_h_pnl: 'PnL ناوگان',
    stress_h_exit: 'هزینهٔ خروج', stress_h_liq: 'لیکویید', stress_h_after: 'اکوییتی بعد',
    stress_h_worst_pos: 'بدترین پوزیشن', stress_h_verdict: 'وضعیت',
    stress_v_ok: 'قابل تحمل', stress_v_hit: 'ضربهٔ جدی', stress_v_critical: 'بحرانی', stress_v_wiped: 'نابودی',

    /* ── capacity ─────────────────────────────────────────────────── */
    nav_capacity: 'ظرفیت',
    title_capacity: 'ظرفیت لبه‌ها', sub_capacity: 'چه سرمایه‌ای را هر لبه قبل از خوردنِ آلفا تحمل می‌کند',
    cap_title: 'ظرفیت لبه‌ها (مدل امپکت √)',
    cap_sub_note: 'امپکت واقعی از هزینهٔ sweep دفتر سفارش (L2) کالیبره می‌شود و در برابر لبهٔ اندازه‌گیری‌شدهٔ OOS هر لبه قرار می‌گیرد؛ ظرفیت = اندازه‌ای که انتظار خالص صفر می‌شود.',
    cap_recalc: 'محاسبهٔ دوباره',
    cap_metrics: 'خلاصه',
    cap_curve_title: 'منحنی لبهٔ خالص در برابر اندازهٔ سفارش',
    cap_table: 'ظرفیت هر لبه',
    cap_empty: 'گزارش ظرفیت در دسترس نیست — ابتدا اسکن لبه‌ها و جمع‌آوری L2 باید اجرا شده باشند.',
    cap_m_edges: 'لبهٔ تحلیل‌شده', cap_m_books: 'دفتر L2', cap_m_median: 'ظرفیت میانه',
    cap_m_zero: 'ظرفیت صفر', cap_m_maxutil: 'بیشترین استفاده',
    cap_net_edge: 'لبهٔ خالص (bps)', cap_impact: 'امپکت رفت‌وبرگشت (bps)',
    cap_capacity_line: 'ظرفیت',
    cap_h_edge: 'لبه/معامله', cap_h_capacity: 'ظرفیت', cap_h_half: 'نیم-لبه',
    cap_h_current: 'سفارش فعلی', cap_h_util: 'استفاده',

    /* edges — statistical rigor */
    edges_rigor_title: 'اعتبار آماری (دفاع در برابر سوگیری انتخاب)',
    edges_rigor_hint: 'با اسکن صدها ترکیب، شارپ بالا تنها وقتی معتبر است که شارپِ تعدیل‌شده (DSR) بالای ۰٫۹۵ بماند و PBO پایین باشد.',
    edges_rigor_trials: 'تعداد آزمون', edges_rigor_pbo: 'PBO میانه', edges_rigor_deflated: 'عبور از Deflated',
    edges_col_psr: 'PSR', edges_col_dsr: 'Deflated SR', edges_col_pbo: 'PBO', edges_col_ci: 'بازهٔ شارپ (۹۵٪)',
    edges_deflated_yes: 'معتبر', edges_deflated_no: 'مشکوک',
    rep_ci_sharpe: 'بازهٔ اطمینان شارپ (۹۵٪)',

    /* cross-exchange */
    cx_pick: 'نماد و تایم‌فریم را انتخاب کنید (نمادهای موجود روی ۲+ صرافی)',
    cx_insufficient: 'این نماد روی کمتر از دو صرافی موجود است',
    cx_venues: 'صرافی‌ها/بازارها', cx_bars: 'تعداد کندل مشترک',
    cx_leadlag: 'پیشرو-پیرو (Lead-Lag)', cx_leadlag_hint: 'لگِ مثبت = ستون A پیشروی B است؛ آربیتراژ تأخیر',
    cx_coint: 'هم‌انباشتگی (Cointegration / Stat-Arb)', cx_coint_hint: 'p-value پایین = اسپرد بازگشت‌به‌میانگین؛ z فعلی فاصله از میانگین',
    cx_basis: 'بیسیس (پرپ در برابر اسپات)', cx_basis_hint: 'اختلاف قیمت مشتقه و اسپات؛ پایهٔ کری/برداشت فاندینگ',
    cx_liquidity: 'نقدینگی (حجم دلاری)',
    cx_col_pair: 'جفت', cx_col_lag: 'لگ', cx_col_corr: 'همبستگی', cx_col_leader: 'پیشرو',
    cx_col_pvalue: 'p-value', cx_col_hedge: 'نسبت هج', cx_col_z: 'z اسپرد', cx_col_coint: 'هم‌انباشته',
    cx_col_spot: 'اسپات', cx_col_deriv: 'مشتقه', cx_col_basis_now: 'بیسیس فعلی', cx_col_basis_mean: 'میانگین', cx_col_basis_std: 'انحراف',
    cx_col_kind: 'نوع', cx_kind_basis: 'پرپ↔اسپات', cx_kind_cross: 'بین‌صرافی',
    cx_scan_btn: 'اسکن خودکار همه', cx_scanning: 'در حال اسکن همهٔ نمادها…',
    cx_scan_title: 'بهترین فرصت‌های بین‌صرافی', cx_scan_hint: 'همهٔ نمادهای دارای ≥۲ صرافی اسکن و بر اساس قدرت لبه رتبه‌بندی شدند؛ ستون «اقدام» ساختار ترید پیشنهادی است.',
    cx_col_type: 'نوع لبه', cx_col_symbol: 'نماد', cx_col_tf: 'تایم‌فریم', cx_col_score: 'امتیاز', cx_col_action: 'اقدام پیشنهادی', cx_col_venues: 'صرافی‌ها',
    cx_col_venue: 'صرافی', cx_col_dvol: 'حجم دلاری',
    cx_col_confidence: 'اطمینان', cx_col_gap: 'فاصله تا میانگین', cx_col_pnl: 'سود تخمینی (سرمایه ۱۰۰۰$)',
    cx_conf_high: 'بالا', cx_conf_medium: 'متوسط', cx_conf_low: 'پایین',
    cx_score_tip: 'امتیاز = قدرت آماری لبه (نه سود تضمینی): برای آربیتراژ آماری = |z| فاصلهٔ اسپرد از میانگین به انحراف معیار؛ برای پیشرو-پیرو = همبستگی×لگ؛ برای کج‌شدگی = انحراف فعلی به انحراف معیار آن. هرچه بالاتر، سیگنال قوی‌تر است.',
    cx_pnl_tip: 'سود تخمینی = اگر این فاصله کامل به میانگین برگردد و ۱۰۰۰ دلار بین دو پایهٔ معامله (لانگ/شورت) تقسیم شود — قبل از کارمزد، فاندینگ، لغزش قیمت (slippage) و بدون تضمین زمان یا وقوع بازگشت.',
    cx_scan_guide_title: '📖 راهنمای استفاده از هر نوع فرصت',
    cx_guide_stat_arb: '🟢 آربیتراژ آماری (Stat-Arb): دو پایه را هم‌زمان باز کنید — طبق ستون «اقدام» یکی را لانگ و دیگری را به نسبت «هج» شورت کنید (مثلاً اگر هج=۱.۰ یعنی اندازهٔ برابر). وقتی z به نزدیک صفر برگشت، هر دو پایه را ببندید. اگر z به جای برگشت، بازهم بیشتر شد (مثلاً از ۳ به ۵ رسید)، یعنی فرضیهٔ هم‌انباشتگی شکسته—با حد ضرر از پوزیشن خارج شوید.',
    cx_guide_lead_lag: '🔵 پیشرو-پیرو (Lead-Lag): این یک معاملهٔ خنثی نیست؛ وقتی صرافی «پیشرو» حرکت می‌کند، همان جهت را روی صرافی «پیرو» با تأخیر چند کندل تکرار کنید. نیاز به اجرای سریع/اتوماتیک دارد و برای ترید دستی عملاً سخت است — بیشتر برای بات مناسب است.',
    cx_guide_dislocation: '🟡 کج‌شدگی بین‌صرافی (Dislocation): قیمت یک نماد روی دو صرافی فاصله گرفته. نماد ارزان‌تر را لانگ و گران‌تر را شورت کنید (هر دو هم‌زمان، با حجم برابر دلاری)، و وقتی فاصله به میانگین تاریخی برگشت ببندید. فاندینگ‌ریت هر صرافی را هم چک کنید چون می‌تواند سود را بخورد یا اضافه کند.',
    cx_guide_disclaimer: '⚠️ این اعداد آماری/تاریخی‌اند، نه پیش‌بینی قطعی. قبل از ورود واقعی: حجم/نقدینگی کافی صرافی‌ها را چک کنید، کارمزد دو طرف معامله و فاندینگ را در نظر بگیرید، و با حجم کوچک تست کنید.',

    /* portfolio */
    pf_select: 'دیتاست‌ها را انتخاب کنید (حداقل ۲)', pf_method: 'روش وزن‌دهی',
    pf_hrp: 'HRP (سلسله‌مراتبی)', pf_risk_parity: 'هم‌ریسک', pf_inverse_vol: 'وارون نوسان', pf_equal: 'وزن برابر',
    pf_build: 'ساخت پرتفوی', pf_need_two: 'حداقل دو دیتاستِ هم‌بازه انتخاب کنید',
    pf_weights: 'وزن‌ها', pf_metrics: 'مشخصات پرتفوی', pf_sizing: 'سایزینگ (Kelly کسری و هدف‌گیری نوسان)',
    pf_div_ratio: 'نسبت تنوع‌بخشی', pf_avg_corr: 'همبستگی میانگین', pf_port_vol: 'نوسان پرتفوی (هر کندل)', pf_n_assets: 'تعداد دارایی',
    pf_col_asset: 'دارایی', pf_col_weight: 'وزن', pf_col_kelly: 'Kelly کسری', pf_col_vol_lev: 'اهرم هدف‌گیری نوسان',
    pf_backtest: 'بک‌تست پرتفوی (در برابر وزن برابر)', pf_beats_ew: 'بهتر از ۱/N', pf_below_ew: 'بدتر از ۱/N',
    pf_backtest_hint: 'بازده واقعیِ سبدِ وزن‌دارِ ساخته‌شده روی همین بازه، در برابر معیارِ ساده‌ی وزن‌برابر (۱/N). اگر زیر ۱/N باشد، روشِ تخصیص ارزش افزوده نداشته.',

    /* models */
    mdl_rl_title: 'پیشنهاد ارز برای RL', mdl_rl_hint: 'مناسب‌ترین ارزها برای ایجنت RL روی فیوچرز ۱۵ دقیقه (Bybit / OKX / Gate)',
    mdl_ml_reco_title: 'پیشنهاد ارز برای ML', mdl_ml_reco_hint: 'مناسب‌ترین ارزها برای مدل ML روی فیوچرز ۱۵ دقیقه (همان امتیازی که چرخش شبانهٔ بات‌های ML استفاده می‌کند)',
    mdl_mf_title: 'جریان پول', mdl_mf_hint: 'کوین‌هایی که سرمایه روی آن‌ها در حال ورود یا خروج است (بر اساس CMF + حجم نسبی + شیب OBV روی کندل‌ها) — همین سیگنال در چرخش شبانه روی امتیازِ انتخاب کوین اثر می‌گذارد.',
    mf_inflow_label: 'ورود پول', mf_outflow_label: 'خروج پول',
    lab_date_hint: 'خالی = کل تاریخچه؛ برای هم‌خوانی با تب گزارش، همان بازهٔ ریسرچ را بگذارید', ins_rerun: 'اعمال بازه',
    mdl_rl_evaluated: 'دیتاست بررسی‌شده', mdl_rl_col_score: 'امتیاز RL', mdl_rl_col_regimes: 'تغییرات رژیم',
    mdl_rl_col_density: 'چگالی پاداش', mdl_rl_col_pred: 'پیش‌بینی‌ناپذیری',
    mdl_ml_title: 'ارزیابی واقعی ML (CV پاک‌سازی‌شده + امبارگو)',
    mdl_ml_hint: 'لیبل سه‌مانعی + Purged K-Fold؛ AUC خارج‌نمونه، بدون نشت اطلاعات (جایگزین امتیاز هیوریستیک).',
    mdl_ml_optimize: 'بهینه‌سازی هایپرپارامتر (Optuna)',
    mdl_ml_auc: 'میانگین AUC', mdl_ml_acc: 'دقت', mdl_ml_folds: 'AUC هر فولد', mdl_ml_verdict: 'حکم',
    verdict_predictable: 'قابل پیش‌بینی', verdict_weak: 'ضعیف', verdict_noise: 'نویز',
    mdl_exp_title: 'دفترچهٔ آزمایش‌ها (بازتولیدپذیری)', mdl_exp_empty: 'هنوز آزمایشی ثبت نشده',
    mdl_exp_col_name: 'نام', mdl_exp_col_metrics: 'متریک‌ها', mdl_exp_col_when: 'زمان', mdl_exp_col_seed: 'seed',

    /* quality + forward-test */
    q_health: 'سلامت داده', q_datasets: 'دیتاست‌ها', q_clean: 'سالم', q_with_gaps: 'دارای شکاف', q_with_malformed: 'خراب',
    q_col_dataset: 'دیتاست', q_col_rows: 'کندل', q_col_coverage: 'پوشش (روز)', q_col_gaps: 'شکاف',
    q_col_dupes: 'تکراری', q_col_malformed: 'خراب', q_col_status: 'وضعیت', q_clean_badge: 'سالم', q_issue_badge: 'مشکل‌دار',
    fwd_title: 'فوروارد-تست: انتظار در برابر تحقق', fwd_hint: 'مقایسهٔ بازده موردانتظار (OOS) با بازده واقعیِ بات‌های زندهٔ بریج.',
    fwd_col_symbol: 'نماد', fwd_col_expected: 'موردانتظار (تقریبی)', fwd_col_realized: 'محقق‌شده',
    fwd_col_trades: 'معاملات', fwd_col_divergence: 'واگرایی', fwd_col_status: 'وضعیت',
    fwd_status_ok: 'منطبق', fwd_status_diverging: 'واگرا', fwd_status_no_trades: 'بدون معامله',
    fwd_no_alerts: 'واگرایی معناداری نیست', fwd_no_data: 'هنوز داده‌ای از بات‌ها نیست',

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
    version_label: 'v1.3',
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
    res_exec_style: 'Execution model', res_exec_taker: 'Taker (fast)', res_exec_maker: 'Maker (order sim)',
    res_real_funding: 'Real funding (saved history, futures only)',
    res_exec_hint: 'Maker: fills only when price trades through the limit + patience/taker-fallback + partial fills under a volume-participation cap',
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
    m_exec_fill_ratio: 'Fill ratio', m_exec_maker_rate: 'Maker fill rate',
    m_exec_fallback: 'Taker fallback', m_exec_missed: 'Missed trades', m_exec_cost: 'Effective cost (bps)',
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
    edges_sub: 'Out-of-sample scan output — the rule-based bridge bots only trade these',
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
    edges_col_status: 'Status',
    edges_deploy_deployable: 'Deployable', edges_deploy_robust: 'Robust', edges_deploy_passed: 'Passed only',
    edges_deploy_legend: '🟢 Deployable = pushed to the bridge bot (robust + bridge-supported rule). 🔵 Robust = cleared the cross-venue/DSR gate but the bridge does not implement it. ⚪ Passed only = cleared just the loose OOS gate (often illiquid / curve-fit). Note: the RL/ML bots are NOT fed by these edges; they pick pairs from the RL/ML fitness score.',
    edges_col_tf: 'TF', edges_col_trades: 'Trades/window',
    edges_dir_both: 'Both', edges_dir_long: 'Long only',
    edges_oos_return: 'OOS return', edges_strategy: 'Strategy', edges_trades_split: 'Trades/window',
    edges_valid_candidates: 'Valid candidates',
    edges_valid_of: '{passed} valid of {scanned}',

    /* ── new navigation + sections (Tiers 0-4) ────────────────────── */
    nav_crossex: 'Cross-Exchange', nav_portfolio: 'Portfolio', nav_models: 'Models', nav_quality: 'Data Quality',
    title_crossex: 'Cross-Exchange Analysis', sub_crossex: 'Edges across venues — lead-lag, cointegration, basis',
    title_portfolio: 'Portfolio Construction', sub_portfolio: 'Correlation-aware weighting & sizing',
    title_models: 'Models (ML/RL)', sub_models: 'Honest ML eval with purged CV + RL recommendation',
    title_quality: 'Data Quality & Forward-Test', sub_quality: 'Feed health + expected-vs-realized attribution',
    analyze: 'Analyze', build: 'Build', evaluate: 'Evaluate', optimize: 'Optimize',
    timeframe: 'Timeframe', symbol_label: 'Symbol', running: 'Running…',

    /* ── fleet risk ───────────────────────────────────────────────── */
    nav_fleet: 'Fleet Risk',
    title_fleet: 'Aggregate Fleet Risk', sub_fleet: 'Exposure, leverage and crowding across all bots at once',
    fleet_title: 'Aggregate Fleet Risk',
    fleet_sub_note: 'Sum of every bot’s open positions: net beta-weighted delta, gross leverage, concentration and correlation — the view no single bot has.',
    fleet_refresh_live: 'Live snapshot',
    fleet_metrics: 'Fleet metrics',
    fleet_exposure_chart: 'Net exposure per asset (β-weighted)',
    fleet_corr_chart: 'Correlation of held assets (30d)',
    fleet_per_bot: 'Per-bot status',
    fleet_positions: 'Open positions (whole fleet)',
    fleet_m_equity: 'Fleet equity', fleet_m_gross: 'Gross notional', fleet_m_net: 'Net notional',
    fleet_m_lev: 'Gross leverage', fleet_m_delta: 'Net β-delta', fleet_m_hhi: 'Concentration (HHI)',
    fleet_m_npos: 'Open positions', fleet_m_corr: 'Avg pairwise corr',
    fleet_h_bot: 'Bot', fleet_h_equity: 'Equity', fleet_h_realized: 'Realized PnL',
    fleet_h_upnl: 'Open PnL', fleet_h_gross: 'Notional', fleet_h_lev: 'Leverage', fleet_h_open: 'Open',
    fleet_h_pair: 'Pair', fleet_h_side: 'Side', fleet_h_stake: 'Stake', fleet_h_notional: 'Notional',
    fleet_h_mark: 'Mark price', fleet_h_age: 'Price age', fleet_h_beta: 'β to BTC',
    fleet_stale: 'stale',
    fleet_ok: 'No risk limit breached — the fleet is inside its envelope.',
    fleet_alert_gross_leverage: 'Fleet gross leverage ({value}x) exceeds the {limit}x cap',
    fleet_alert_net_delta: 'Fleet net β-delta ({value}% of equity) exceeds the {limit}% limit',
    fleet_alert_asset_concentration: 'Concentration in {context}: {value}% of gross (limit {limit}%)',
    fleet_alert_bot_leverage: 'Bot {context} gross leverage is {value}x (limit {limit}x)',
    fleet_alert_bot_db_missing: 'Bot {context} database is unreachable',
    fleet_alert_crowding_corr: 'Average correlation of held assets is {value} (limit {limit}) — crowding risk',
    fleet_empty: 'No open positions in the fleet, or local.json is not configured.',

    /* ── alt-data ─────────────────────────────────────────────────── */
    nav_altdata: 'Alt-Data',
    title_altdata: 'Alt-Data', sub_altdata: 'Positioning, implied vol (DVOL), basis term structure, liquidations',
    alt_title: 'Alt-data: positioning, implied vol, basis, liquidations',
    alt_sub_note: 'Regime detection fed only on realized data until now; these are the market’s forward-looking state: priced vol, crowd skew, carry, and forced flow.',
    alt_refresh: 'Fetch live',
    alt_metrics: 'Current state',
    alt_dvol_chart: 'Bitcoin DVOL (30d implied vol)',
    alt_ls_chart: 'Account long/short ratio (BTC)',
    alt_term_chart: 'Basis term structure (annualized %)',
    alt_extremes: 'Venue funding extremes',
    alt_liq: 'Liquidation tape (OKX BTC)',
    alt_m_ls: 'Account L/S (BTC)', alt_m_taker: 'Taker ratio (BTC)',
    alt_m_liq24: 'Liquidations 24h', alt_m_perp_basis: 'Perp carry (ann.)',
    alt_h_funding_ann: 'Funding (ann.)', alt_h_premium: 'Premium (bps)',
    alt_h_time: 'Time', alt_h_side: 'Side', alt_h_notional: 'Notional',
    alt_shorts_liq: 'shorts liquidated', alt_longs_liq: 'longs liquidated',
    alt_no_hints: 'No extreme regime signals in the alt-data.',
    alt_hint_dvol_high: 'DVOL is in the top decile of its recent history — implied vol stretched; trim size and leverage.',
    alt_hint_dvol_low: 'DVOL is in the bottom decile of its recent history — vol is cheap and the market calm; regime-break risk.',
    alt_hint_crowd_long: 'The crowd is heavily long (L/S ≥ 3) — cascading-liquidation risk on a selloff.',
    alt_hint_crowd_short: 'The crowd is heavily short (L/S ≤ 0.7) — short-squeeze risk.',
    alt_hint_backwardation: 'The term structure is in backwardation — derivative-market stress/selling pressure.',

    /* ── pipeline health ──────────────────────────────────────────── */
    nav_pipeline: 'Pipeline Health',
    title_pipeline: 'Pipeline Heartbeat', sub_pipeline: 'Every scheduled job must leave a fresh artifact — audited in one sweep',
    pipe_title: 'Pipeline heartbeat',
    pipe_sub_note: 'A wiped crontab, dead watcher or full disk kills nightly jobs silently. This audits the freshness of every registered job’s artifact; a stale critical job raises the alarm.',
    pipe_audit: 'Audit now',
    pipe_jobs: 'Job status',
    pipe_history: 'Health history (per audit)',
    pipe_history_empty: 'No history yet — every audit run adds a point.',
    pipe_all_ok: 'All {n} jobs have fresh artifacts — the pipeline is healthy.',
    pipe_failing: '{late} jobs late and {missing} missing artifacts',
    pipe_s_ok: 'fresh', pipe_s_late: 'late', pipe_s_missing: 'missing',
    pipe_age: 'Age',

    /* ── attribution ──────────────────────────────────────────────── */
    nav_attribution: 'Attribution',
    title_attribution: 'PnL Attribution', sub_attribution: 'Every dollar of PnL: decision alpha, slippage, fees, funding, MFE capture',
    attr_title: 'PnL attribution — where did each dollar go?',
    attr_sub_note: 'Each closed trade decomposes into five parts: the alpha the strategy decided, what entry/exit slippage gave back, what fees took, funding, and a residual. This separates alpha decay from execution decay.',
    attr_recalc: 'Compute',
    attr_totals: 'Fleet totals',
    attr_waterfall: 'PnL waterfall',
    attr_capture_chart: 'Mean MFE capture per bot',
    attr_bot_table: 'Per-bot breakdown',
    attr_reason_table: 'Exit-reason breakdown (selected bot)',
    attr_fleet: 'Whole fleet',
    attr_m_intended: 'Decision alpha', attr_m_slip: 'Slippage', attr_m_fees: 'Fees',
    attr_m_funding: 'Funding', attr_m_net: 'Net', attr_m_residual: 'Residual',
    attr_w_entry_slip: 'Entry slippage', attr_w_exit_slip: 'Exit slippage',
    attr_h_trades: 'Trades', attr_h_reason: 'Exit reason',

    /* ── trial ledger ─────────────────────────────────────────────── */
    nav_trials: 'Trial Ledger',
    title_trials: 'Trial Ledger', sub_trials: 'The cumulative multiple-testing account — DSR against every hypothesis ever tried',
    trials_title: 'Trial Ledger (edge graveyard)',
    trials_sub_note: 'Nightly scans deflate Sharpe only by that night’s trials, but selection bias compounds across nights. This ledger records every unique hypothesis once and recomputes the honest DSR against the entire search history.',
    trials_metrics: 'Cumulative account',
    trials_timeline: 'Cumulative unique hypotheses over time',
    trials_strategies: 'Strategy breakdown',
    trials_top: 'Top edges: nightly vs cumulative DSR',
    trials_empty: 'The ledger is still empty — the next nightly scan will record every tested hypothesis.',
    trials_empty_short: 'Nothing recorded yet — waiting for the first scan.',
    trials_m_unique: 'Unique hypotheses', trials_m_runs: 'Total runs', trials_m_tonight: 'Latest scan',
    trials_m_passed: 'Ever passed', trials_m_srvar: 'Sharpe variance',
    trials_cumulative: 'Cumulative', trials_new: 'New per day',
    trials_h_hyps: 'Hypotheses', trials_h_passed: 'Passed', trials_h_passrate: 'Pass rate',
    trials_h_bestsr: 'Best SR/bar',
    trials_h_dsr_night: 'Nightly DSR', trials_h_dsr_cum: 'Cumulative DSR', trials_h_verdict: 'Verdict',
    trials_demoted: 'fails at cumulative count', trials_survives: 'survives cumulative deflation',

    /* ── stress ───────────────────────────────────────────────────── */
    nav_stress: 'Stress Test',
    title_stress: 'Portfolio Stress Test', sub_stress: 'Tail-event replays + parametric shocks on the live book',
    stress_title: 'Live-book stress testing',
    stress_sub_note: 'Every scenario runs against the fleet’s current open positions: β-scaled asset moves, isolated-margin liquidations, concurrent funding and the cost of flattening into a stressed book.',
    stress_run: 'Run scenarios',
    stress_summary: 'Summary',
    stress_chart: 'Equity impact per scenario (%)',
    stress_path_chart: 'BTC path in the historical scenario',
    stress_table: 'Scenario details',
    stress_empty: 'No open positions to stress.',
    stress_fallback: 'Local data misses this window — documented historical move used',
    stress_m_equity: 'Equity', stress_m_positions: 'Open positions', stress_m_worst: 'Worst scenario',
    stress_m_worst_pnl: 'Worst-case loss', stress_m_liq: 'Max liquidations',
    stress_h_scenario: 'Scenario', stress_h_move: 'Market move', stress_h_pnl: 'Fleet PnL',
    stress_h_exit: 'Exit cost', stress_h_liq: 'Liq.', stress_h_after: 'Equity after',
    stress_h_worst_pos: 'Worst position', stress_h_verdict: 'Verdict',
    stress_v_ok: 'survivable', stress_v_hit: 'serious hit', stress_v_critical: 'critical', stress_v_wiped: 'wiped out',

    /* ── capacity ─────────────────────────────────────────────────── */
    nav_capacity: 'Capacity',
    title_capacity: 'Edge Capacity', sub_capacity: 'How much size each edge carries before impact eats the alpha',
    cap_title: 'Edge Capacity (√-impact model)',
    cap_sub_note: 'Impact is calibrated from real L2 order-book sweep costs and set against each edge’s measured OOS alpha; capacity = the size where net expectancy hits zero.',
    cap_recalc: 'Recalculate',
    cap_metrics: 'Summary',
    cap_curve_title: 'Net edge vs order size',
    cap_table: 'Per-edge capacity',
    cap_empty: 'No capacity report yet — run the edge scan and L2 collection first.',
    cap_m_edges: 'Edges analysed', cap_m_books: 'L2 books', cap_m_median: 'Median capacity',
    cap_m_zero: 'Zero capacity', cap_m_maxutil: 'Max utilization',
    cap_net_edge: 'Net edge (bps)', cap_impact: 'Round-trip impact (bps)',
    cap_capacity_line: 'capacity',
    cap_h_edge: 'Edge/trade', cap_h_capacity: 'Capacity', cap_h_half: 'Half-edge',
    cap_h_current: 'Current order', cap_h_util: 'Utilization',

    /* edges — statistical rigor */
    edges_rigor_title: 'Statistical rigor (selection-bias defences)',
    edges_rigor_hint: 'After scanning hundreds of combos, a high Sharpe is only credible if its Deflated Sharpe (DSR) stays above 0.95 and PBO is low.',
    edges_rigor_trials: 'Trials', edges_rigor_pbo: 'Median PBO', edges_rigor_deflated: 'Pass deflation',
    edges_col_psr: 'PSR', edges_col_dsr: 'Deflated SR', edges_col_pbo: 'PBO', edges_col_ci: 'Sharpe CI (95%)',
    edges_deflated_yes: 'credible', edges_deflated_no: 'suspect',
    rep_ci_sharpe: 'Sharpe confidence interval (95%)',

    /* cross-exchange */
    cx_pick: 'Pick a symbol and timeframe (symbols available on 2+ venues)',
    cx_insufficient: 'This symbol is available on fewer than two venues',
    cx_venues: 'Venues/markets', cx_bars: 'Common bars',
    cx_leadlag: 'Lead-Lag', cx_leadlag_hint: 'Positive lag = column A leads B; latency arbitrage',
    cx_coint: 'Cointegration (Stat-Arb)', cx_coint_hint: 'Low p-value = mean-reverting spread; z = current distance from mean',
    cx_basis: 'Basis (perp vs spot)', cx_basis_hint: 'Derivative-vs-spot price gap; basis of carry / funding harvest',
    cx_liquidity: 'Liquidity (dollar volume)',
    cx_col_pair: 'Pair', cx_col_lag: 'Lag', cx_col_corr: 'Corr', cx_col_leader: 'Leader',
    cx_col_pvalue: 'p-value', cx_col_hedge: 'Hedge ratio', cx_col_z: 'Spread z', cx_col_coint: 'Cointegrated',
    cx_col_spot: 'Spot', cx_col_deriv: 'Derivative', cx_col_basis_now: 'Basis now', cx_col_basis_mean: 'Mean', cx_col_basis_std: 'Std',
    cx_col_kind: 'Kind', cx_kind_basis: 'perp↔spot', cx_kind_cross: 'cross-venue',
    cx_scan_btn: 'Auto-scan all', cx_scanning: 'Scanning all symbols…',
    cx_scan_title: 'Top cross-exchange opportunities', cx_scan_hint: 'Every symbol on ≥2 venues was scanned and ranked by edge strength; the Action column is the suggested trade construction.',
    cx_col_type: 'Edge type', cx_col_symbol: 'Symbol', cx_col_tf: 'Timeframe', cx_col_score: 'Score', cx_col_action: 'Suggested action', cx_col_venues: 'Venues',
    cx_col_venue: 'Venue', cx_col_dvol: 'Dollar volume',
    cx_col_confidence: 'Confidence', cx_col_gap: 'Gap to mean', cx_col_pnl: 'Est. PnL ($1000)',
    cx_conf_high: 'High', cx_conf_medium: 'Medium', cx_conf_low: 'Low',
    cx_score_tip: 'Score = statistical strength of the edge (not guaranteed profit): for stat-arb it is |z| (spread distance from mean, in std-devs); for lead-lag it is correlation×lag; for dislocation it is the current deviation divided by its own std. Higher = stronger signal.',
    cx_pnl_tip: 'Estimated PnL = if this gap fully reverts to the mean and $1000 is split across both legs (long/short) of the trade — gross, before fees, funding and slippage, with no guarantee of timing or whether it reverts at all.',
    cx_scan_guide_title: '📖 How to use each opportunity type',
    cx_guide_stat_arb: '🟢 Stat-Arb: open both legs at once — long one side, short the other sized by the hedge ratio in the Action column (e.g. hedge=1.0 means equal size). Close both legs once z returns near zero. If z keeps widening instead of reverting (e.g. 3 → 5), the cointegration assumption is breaking down — exit with a stop.',
    cx_guide_lead_lag: '🔵 Lead-Lag: not a market-neutral trade; when the "leader" venue moves, mirror the same direction on the "follower" venue a few bars later. Requires fast/automated execution — impractical by hand, best suited to a bot.',
    cx_guide_dislocation: '🟡 Dislocation: the same symbol has diverged in price across two venues. Long the cheaper venue and short the pricier one (simultaneously, equal dollar size), close once the gap reverts to its historical mean. Check each venue\'s funding rate too — it can eat into or add to the profit.',
    cx_guide_disclaimer: '⚠️ These numbers are statistical/historical, not a guarantee. Before trading real size: check each venue has enough liquidity, account for fees on both legs plus funding, and test with a small position first.',

    /* portfolio */
    pf_select: 'Select datasets (at least 2)', pf_method: 'Weighting method',
    pf_hrp: 'HRP (hierarchical)', pf_risk_parity: 'Risk Parity', pf_inverse_vol: 'Inverse Vol', pf_equal: 'Equal Weight',
    pf_build: 'Build Portfolio', pf_need_two: 'Select at least two time-overlapping datasets',
    pf_weights: 'Weights', pf_metrics: 'Portfolio profile', pf_sizing: 'Sizing (fractional Kelly & vol-targeting)',
    pf_div_ratio: 'Diversification ratio', pf_avg_corr: 'Avg correlation', pf_port_vol: 'Portfolio vol (per bar)', pf_n_assets: 'Assets',
    pf_col_asset: 'Asset', pf_col_weight: 'Weight', pf_col_kelly: 'Fractional Kelly', pf_col_vol_lev: 'Vol-target leverage',
    pf_backtest: 'Portfolio backtest (vs equal-weight)', pf_beats_ew: 'Beats 1/N', pf_below_ew: 'Below 1/N',
    pf_backtest_hint: 'Realized return of the weighted basket over this window vs the naive equal-weight (1/N) benchmark. If it sits below 1/N, the allocation method added no value.',

    /* models */
    mdl_rl_title: 'RL Coin Recommendation', mdl_rl_hint: 'Best coins for an RL agent on 15m futures (Bybit / OKX / Gate)',
    mdl_ml_reco_title: 'ML Coin Recommendation', mdl_ml_reco_hint: 'Best coins for an ML model on 15m futures (the same score the nightly ML-bot rotation uses)',
    mdl_mf_title: 'Money Flow', mdl_mf_hint: 'Coins capital is currently rotating into or out of (CMF + relative volume + OBV slope on candles) — the same signal tilts coin-selection scores in the nightly rotation.',
    mf_inflow_label: 'Inflow', mf_outflow_label: 'Outflow',
    lab_date_hint: 'Empty = full history; to match the Report tab, use the same Research range', ins_rerun: 'Apply range',
    mdl_rl_evaluated: 'datasets evaluated', mdl_rl_col_score: 'RL score', mdl_rl_col_regimes: 'Regime changes',
    mdl_rl_col_density: 'Reward density', mdl_rl_col_pred: 'Unpredictability',
    mdl_ml_title: 'Honest ML Evaluation (purged + embargoed CV)',
    mdl_ml_hint: 'Triple-barrier labels + Purged K-Fold; out-of-sample AUC with no leakage (replaces the heuristic score).',
    mdl_ml_optimize: 'Tune hyperparameters (Optuna)',
    mdl_ml_auc: 'Mean AUC', mdl_ml_acc: 'Accuracy', mdl_ml_folds: 'Per-fold AUC', mdl_ml_verdict: 'Verdict',
    verdict_predictable: 'predictable', verdict_weak: 'weak', verdict_noise: 'noise',
    mdl_exp_title: 'Experiment ledger (reproducibility)', mdl_exp_empty: 'No experiments logged yet',
    mdl_exp_col_name: 'Name', mdl_exp_col_metrics: 'Metrics', mdl_exp_col_when: 'When', mdl_exp_col_seed: 'seed',

    /* quality + forward-test */
    q_health: 'Data health', q_datasets: 'Datasets', q_clean: 'Clean', q_with_gaps: 'With gaps', q_with_malformed: 'Malformed',
    q_col_dataset: 'Dataset', q_col_rows: 'Bars', q_col_coverage: 'Coverage (days)', q_col_gaps: 'Gaps',
    q_col_dupes: 'Dupes', q_col_malformed: 'Malformed', q_col_status: 'Status', q_clean_badge: 'clean', q_issue_badge: 'issues',
    fwd_title: 'Forward-Test: expected vs realized', fwd_hint: 'Compares expected (OOS) return with the live bridge bots’ realized return.',
    fwd_col_symbol: 'Symbol', fwd_col_expected: 'Expected (approx)', fwd_col_realized: 'Realized',
    fwd_col_trades: 'Trades', fwd_col_divergence: 'Divergence', fwd_col_status: 'Status',
    fwd_status_ok: 'on-track', fwd_status_diverging: 'diverging', fwd_status_no_trades: 'no trades',
    fwd_no_alerts: 'no meaningful divergence', fwd_no_data: 'no live bot data yet',

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
