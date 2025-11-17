// ===== Tab Navigation =====
const tabButtons = document.querySelectorAll('.tab-button');
const tabPanes = document.querySelectorAll('.tab-pane');

tabButtons.forEach(button => {
    button.addEventListener('click', () => {
        const targetTab = button.dataset.tab;
        
        // Remove active class from all buttons and panes
        tabButtons.forEach(btn => btn.classList.remove('active'));
        tabPanes.forEach(pane => pane.classList.remove('active'));
        
        // Add active class to clicked button and corresponding pane
        button.classList.add('active');
        document.getElementById(targetTab).classList.add('active');
    });
});

// ===== Utility Functions =====
function showLoader(button) {
    const btnText = button.querySelector('.btn-text');
    const loader = button.querySelector('.loader');
    if (btnText) btnText.classList.add('hidden');
    if (loader) loader.classList.remove('hidden');
    button.disabled = true;
}

function hideLoader(button) {
    const btnText = button.querySelector('.btn-text');
    const loader = button.querySelector('.loader');
    if (btnText) btnText.classList.remove('hidden');
    if (loader) loader.classList.add('hidden');
    button.disabled = false;
}

// Sanitize HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Форматирование режима налогообложения
function formatTaxMode(mode) {
    if (!mode) return '';
    
    // Преобразуем техническое название в читаемое
    if (mode === 'УСН_доходы') {
        return 'УСН Доходы';
    } else if (mode === 'УСН_доходы_минус_расходы') {
        return 'УСН Доходы минус расходы';
    }
    
    // Если формат уже читаемый (из налогового планирования), возвращаем как есть
    // Иначе заменяем подчеркивания на пробелы
    return mode.replace(/_/g, ' ');
}

// Форматирование даты в дд.мм.гг
function formatDate(dateStr) {
    if (!dateStr || dateStr.trim() === '' || dateStr === '—') {
        return '—';
    }
    
    try {
        // Обрабатываем разные форматы
        let dateStrClean = String(dateStr).trim();
        if (dateStrClean.includes('T')) {
            dateStrClean = dateStrClean.split('T')[0];
        }
        
        // Парсим YYYY-MM-DD
        const match = dateStrClean.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (match) {
            const day = match[3];
            const month = match[2];
            const year = match[1].slice(-2); // Последние 2 цифры года
            return `${day}.${month}.${year}`;
        }
        
        // Если уже в формате дд.мм.гг, возвращаем как есть
        if (dateStrClean.match(/^\d{2}\.\d{2}\.\d{2}$/)) {
            return dateStrClean;
        }
        
        // Пробуем распарсить через Date
        const date = new Date(dateStrClean);
        if (!isNaN(date.getTime())) {
            const day = String(date.getDate()).padStart(2, '0');
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const year = String(date.getFullYear()).slice(-2);
            return `${day}.${month}.${year}`;
        }
        
        return dateStr; // Если не удалось распарсить, возвращаем как есть
    } catch (e) {
        console.warn('[formatDate] Error formatting date:', dateStr, e);
        return dateStr;
    }
}

function showResult(resultId, content, isError = false) {
    const resultDiv = document.getElementById(resultId);
    if (!resultDiv) return;
    
    // For trusted HTML content (our templates), use innerHTML
    // For error messages, content is already sanitized via escapeHtml
    resultDiv.innerHTML = content;
    resultDiv.style.display = 'block';
    resultDiv.classList.remove('hidden');
    
    // Scroll to result
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function formatNumber(num) {
    return new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(num);
}

// ===== Transaction Analyzer =====
const transactionForm = document.getElementById('transactionForm');
if (transactionForm) {
    transactionForm.addEventListener('submit', async (e) => {
        e.preventDefault();
    
    const form = e.target;
    const submitButton = form.querySelector('button[type="submit"]');
    const fileInput = document.getElementById('transactionFile');
    const taxModeInput = form.querySelector('input[name="tax_mode"]:checked');
    
    if (!fileInput.files[0]) {
        showResult('transactionResult', 
            '<p class="error-message">⚠️ Пожалуйста, выберите файл</p>', true);
        return;
    }
    
    showLoader(submitButton);
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('tax_mode', taxModeInput.value);
    
    try {
        const response = await fetch('/api/analyze-transactions', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok && response.status >= 500) {
            throw new Error('Сервер временно недоступен. Попробуйте позже.');
        }
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Ошибка при анализе транзакций');
        }
        
        // Format result
        const summary = data.summary;
        const transactions = data.transactions;
        const anomalies = data.anomalies || [];
        const plReport = data.pl_report || {};
        const forecasts = data.forecasts || {};
        
        // Sanitize user data before inserting into HTML
        const formattedMode = formatTaxMode(summary.mode || '');
        const safeMode = escapeHtml(formattedMode);
        const safeTransactions = summary.transactions || 0;
        const safeTax = formatNumber(summary.tax);
        
        let html = `
            <div class="summary-box">
                <div class="summary-header">Результаты анализа</div>
                <div class="summary-grid">
                    <div class="summary-card">
                        <div class="summary-label">Режим налогообложения</div>
                        <div class="summary-value-main">${safeMode}</div>
                    </div>
                    <div class="summary-card">
                        <div class="summary-label">Количество транзакций</div>
                        <div class="summary-value-main">${safeTransactions}</div>
                    </div>
                    <div class="summary-card summary-card-highlight">
                        <div class="summary-label">Налог к уплате</div>
                        <div class="summary-value-large">${safeTax}<span class="currency">₽</span></div>
                    </div>
                </div>
            </div>
        `;
        
        // Управленческий P&L
        if (plReport.revenue !== undefined) {
            html += `
                <div class="analytics-section">
                    <h3>Управленческий P&L</h3>
                    <div class="pl-report">
                        <div class="pl-row">
                            <span class="pl-label">Выручка:</span>
                            <span class="pl-value">${formatNumber(plReport.revenue)} ₽</span>
                        </div>
                        <div class="pl-row">
                            <span class="pl-label">Себестоимость (COGS):</span>
                            <span class="pl-value">${formatNumber(plReport.cogs)} ₽</span>
                        </div>
                        <div class="pl-row pl-highlight">
                            <span class="pl-label">Валовая прибыль:</span>
                            <span class="pl-value">${formatNumber(plReport.gross_profit)} ₽ (${plReport.gross_margin?.toFixed(1)}%)</span>
                        </div>
                        <div class="pl-row">
                            <span class="pl-label">Операционные расходы:</span>
                            <span class="pl-value">${formatNumber(plReport.operating_expenses)} ₽</span>
                        </div>
                        <div class="pl-row pl-highlight">
                            <span class="pl-label">Операционная прибыль (EBITDA):</span>
                            <span class="pl-value">${formatNumber(plReport.operating_profit)} ₽ (${plReport.operating_margin?.toFixed(1)}%)</span>
                        </div>
                    </div>
                </div>
            `;
        }
        
        // Визуализации
        if (data.detailed_transactions && data.detailed_transactions.length > 0) {
            html += `
                <div class="analytics-section">
                    <h3>Визуализация данных</h3>
                    <div class="charts-container">
                        <div class="chart-wrapper">
                            <h4 style="margin-bottom: 12px; font-size: 16px; font-weight: 600;">Расходы по категориям</h4>
                            <canvas id="expensesPieChart" style="max-height: 300px;"></canvas>
                        </div>
                        <div class="chart-wrapper">
                            <h4 style="margin-bottom: 12px; font-size: 16px; font-weight: 600;">Динамика доходов и расходов</h4>
                            <canvas id="incomeExpensesChart" style="max-height: 300px;"></canvas>
                        </div>
                        <div class="chart-wrapper" id="periodComparisonChartWrapper" style="display: none;">
                            <h4 style="margin-bottom: 12px; font-size: 16px; font-weight: 600;">Сравнение периодов</h4>
                            
                            <!-- Фильтры для выбора периода -->
                            <div id="periodComparisonFilters" style="margin-bottom: 16px; padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-sm);">
                                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px;">
                                    <div>
                                        <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">Текущий период (от)</label>
                                        <input type="date" id="currentPeriodStart" class="filter-input" style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
                                    </div>
                                    <div>
                                        <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">Текущий период (до)</label>
                                        <input type="date" id="currentPeriodEnd" class="filter-input" style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
                                    </div>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px;">
                                    <div>
                                        <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">Предыдущий период (от)</label>
                                        <input type="date" id="previousPeriodStart" class="filter-input" style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
                                    </div>
                                    <div>
                                        <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">Предыдущий период (до)</label>
                                        <input type="date" id="previousPeriodEnd" class="filter-input" style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
                                    </div>
                                </div>
                                <div style="display: flex; gap: 8px;">
                                    <button onclick="updatePeriodComparison()" class="btn" style="background: var(--primary-color); color: white; padding: 8px 16px; border: none; border-radius: var(--radius-sm); cursor: pointer;">
                                        <span class="btn-text">Применить фильтр</span>
                                    </button>
                                    <button onclick="resetPeriodComparison()" class="btn" style="background: var(--bg-secondary); border: 1px solid var(--border-color); padding: 8px 16px; border-radius: var(--radius-sm); cursor: pointer;">
                                        <span class="btn-text">Сбросить</span>
                                    </button>
                                </div>
                                <div style="margin-top: 12px; font-size: 12px; color: var(--text-secondary);">
                                    <small>Оставьте поля предыдущего периода пустыми для автоматического расчета</small>
                                </div>
                            </div>
                            
                            <div style="margin-bottom: 16px; font-size: 13px; color: var(--text-secondary);">
                                <div id="periodComparisonInfo"></div>
                            </div>
                            <canvas id="periodComparisonChart" style="max-height: 300px;"></canvas>
                        </div>
                        <div class="chart-wrapper" id="waterfallChartWrapper" style="display: none;">
                            <h4 style="margin-bottom: 12px; font-size: 16px; font-weight: 600;">P&L Waterfall</h4>
                            <canvas id="waterfallChart" style="max-height: 300px;"></canvas>
                        </div>
                    </div>
                </div>
            `;
        }
        
        // Бенчмаркинг
        if (data.benchmarking && data.benchmarking.available) {
            html += `
                <div class="analytics-section" style="margin-top: 24px;">
                    <h3>Сравнение с индустрией</h3>
                    <div class="benchmarking-list" style="margin-top: 16px;">
            `;
            
            data.benchmarking.comparisons.forEach(comp => {
                const statusClass = comp.status === 'good' ? 'forecast-info' : 'forecast-warning';
                html += `
                    <div class="forecast-item ${statusClass}" style="margin-bottom: 12px;">
                        <div class="forecast-title">${escapeHtml(comp.metric)}</div>
                        <div style="display: flex; justify-content: space-between; margin-top: 8px;">
                            <span style="font-size: 14px; color: var(--text-secondary);">Ваш показатель: <strong>${escapeHtml(comp.current)}</strong></span>
                            <span style="font-size: 14px; color: var(--text-secondary);">Средний по отрасли: <strong>${escapeHtml(comp.benchmark)}</strong></span>
                        </div>
                        <div class="forecast-message" style="margin-top: 8px;">${escapeHtml(comp.message)}</div>
                    </div>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        }
        
        // Налоговое планирование
        if (data.tax_planning && data.tax_planning.available) {
            html += `
                <div class="analytics-section" style="margin-top: 24px;">
                    <h3>Налоговое планирование на год</h3>
                    <div style="margin-top: 16px;">
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 20px;">
                            <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-md);">
                                <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Прогноз доходов (год)</div>
                                <div style="font-size: 20px; font-weight: 600; color: var(--text-primary);">${formatNumber(data.tax_planning.annual_forecast.income)} ₽</div>
                            </div>
                            <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-md);">
                                <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Прогноз расходов (год)</div>
                                <div style="font-size: 20px; font-weight: 600; color: var(--text-primary);">${formatNumber(data.tax_planning.annual_forecast.expenses)} ₽</div>
                            </div>
                            <div style="padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-md);">
                                <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Оптимальный налог (год)</div>
                                <div style="font-size: 20px; font-weight: 600; color: var(--accent-color);">${formatNumber(data.tax_planning.optimal_scenario.tax)} ₽</div>
                            </div>
                        </div>
                        
                        <div style="margin-top: 16px;">
                            <h4 style="font-size: 16px; font-weight: 600; margin-bottom: 12px;">Сценарии налогообложения</h4>
                            <table class="transaction-table" style="width: 100%;">
                                <thead>
                                    <tr>
                                        <th>Режим</th>
                                        <th style="text-align: right;">Налог (год)</th>
                                        <th style="text-align: right;">Эффективная ставка</th>
                                    </tr>
                                </thead>
                                <tbody>
            `;
            
            data.tax_planning.tax_scenarios.forEach(scenario => {
                const isOptimal = scenario.mode === data.tax_planning.optimal_scenario.mode;
                const rowStyle = isOptimal ? 'background: rgba(34, 197, 94, 0.1);' : '';
                const formattedMode = formatTaxMode(scenario.mode);
                html += `
                    <tr style="${rowStyle}">
                        <td>${escapeHtml(formattedMode)}${isOptimal ? ' <span style="color: var(--accent-color);">(оптимально)</span>' : ''}</td>
                        <td style="text-align: right; font-weight: 600;">${formatNumber(scenario.tax)} ₽</td>
                        <td style="text-align: right;">${scenario.effective_rate.toFixed(2)}%</td>
                    </tr>
                `;
            });
            
            html += `
                                </tbody>
                            </table>
                        </div>
            `;
            
            if (data.tax_planning.recommendations && data.tax_planning.recommendations.length > 0) {
                html += `<div style="margin-top: 20px;">`;
                data.tax_planning.recommendations.forEach(rec => {
                    html += `
                        <div class="forecast-item forecast-info" style="margin-bottom: 12px;">
                            <div class="forecast-title">${escapeHtml(rec.title)}</div>
                            <div class="forecast-message">${escapeHtml(rec.message)}</div>
                        </div>
                    `;
                });
                html += `</div>`;
            }
            
            html += `
                    </div>
                </div>
            `;
        }
        
        // Фильтры
        if (data.detailed_transactions && data.detailed_transactions.length > 0) {
            const categories = [...new Set(data.detailed_transactions.map(t => t.Категория).filter(c => c && c !== 'Поступление от клиента'))];
            html += `
                <div class="analytics-section" style="margin-top: 24px;">
                    <h3>Детализация транзакций</h3>
                    <div class="filters-container" style="margin-bottom: 16px;">
                        <!-- Фильтр по категории (как в истории) -->
                        <div style="margin-bottom: 12px;">
                            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 8px; color: var(--text-secondary);">Категория</label>
                            <div class="history-filter-dropdown">
                                <button type="button" class="history-filter-trigger" id="transactionCategoryFilterTrigger">
                                    <span class="filter-trigger-text">Все категории</span>
                                    <svg class="filter-arrow" width="12" height="8" viewBox="0 0 12 8" fill="none">
                                        <path d="M1 1L6 6L11 1" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <div class="history-filter-menu" id="transactionCategoryFilterMenu">
                                    <input type="radio" id="tx-filter-all" name="transactionCategoryFilter" value="" checked hidden>
                                    <label for="tx-filter-all" class="history-filter-option" data-label="Все категории">Все категории</label>
                                    ${categories.map((cat, idx) => `
                                        <input type="radio" id="tx-filter-${idx}" name="transactionCategoryFilter" value="${escapeHtml(cat)}" hidden>
                                        <label for="tx-filter-${idx}" class="history-filter-option" data-label="${escapeHtml(cat)}">${escapeHtml(cat)}</label>
                                    `).join('')}
                                </div>
                            </div>
                        </div>
                        
                        <!-- Фильтры по датам -->
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px;">
                            <div>
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">С даты</label>
                                <input type="date" id="dateFromFilter" class="filter-input" style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
                            </div>
                            <div>
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">По дату</label>
                                <input type="date" id="dateToFilter" class="filter-input" style="width: 100%; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
                            </div>
                        </div>
                        
                        <div style="display: flex; gap: 8px;">
                            <button onclick="applyFilters()" class="btn btn-primary" style="padding: 8px 16px;">Применить фильтры</button>
                            <button onclick="resetFilters()" class="btn" style="padding: 8px 16px; background: var(--bg-secondary); border: 1px solid var(--border-color);">Сбросить</button>
                        </div>
                    </div>
                    <div id="filteredTransactionsTable"></div>
                </div>
            `;
        }
        
        // Аномалии
        if (anomalies && anomalies.length > 0) {
            html += `
                <div class="analytics-section">
                    <h3>Обнаруженные аномалии</h3>
                    <div class="anomalies-list">
            `;
            
            anomalies.forEach(anomaly => {
                const severityClass = anomaly.severity === 'high' ? 'anomaly-high' : 'anomaly-medium';
                html += `
                    <div class="anomaly-item ${severityClass}">
                        <div class="anomaly-type">${escapeHtml(anomaly.type)}</div>
                        <div class="anomaly-description">${escapeHtml(anomaly.description)}</div>
                    </div>
                `;
            });
            
            html += `
                    </div>
                </div>
            `;
        }
        
        // Прогнозы и рекомендации
        if (forecasts.forecast_30d_expenses !== undefined) {
            html += `
                <div class="analytics-section">
                    <h3>Прогнозы и рекомендации</h3>
            `;
            
            // Прогноз на 30 дней с confidence intervals
            if (forecasts.confidence_intervals) {
                const ci = forecasts.confidence_intervals;
                html += `
                    <div class="forecast-summary">
                        <div class="forecast-row">
                            <span class="forecast-label">Прогноз расходов (30 дней):</span>
                            <span class="forecast-value">${formatNumber(forecasts.forecast_30d_expenses)} ₽</span>
                        </div>
                        <div class="forecast-ci">
                            Доверительный интервал: ${formatNumber(ci.expenses.lower)} - ${formatNumber(ci.expenses.upper)} ₽
                        </div>
                        
                        <div class="forecast-row">
                            <span class="forecast-label">Прогноз доходов (30 дней):</span>
                            <span class="forecast-value">${formatNumber(forecasts.forecast_30d_income)} ₽</span>
                        </div>
                        <div class="forecast-ci">
                            Доверительный интервал: ${formatNumber(ci.income.lower)} - ${formatNumber(ci.income.upper)} ₽
                        </div>
                        
                        <div class="forecast-row forecast-highlight">
                            <span class="forecast-label">Прогноз баланса (30 дней):</span>
                            <span class="forecast-value ${forecasts.forecast_30d_balance < 0 ? 'forecast-negative' : 'forecast-positive'}">${formatNumber(forecasts.forecast_30d_balance)} ₽</span>
                        </div>
                        <div class="forecast-ci">
                            Диапазон: ${formatNumber(ci.balance.lower)} - ${formatNumber(ci.balance.upper)} ₽
                        </div>
                    </div>
                `;
            }
            
            // Сезонные факторы
            if (forecasts.seasonal_factors) {
                const sf = forecasts.seasonal_factors;
                if (Math.abs(sf.expenses - 1.0) > 0.05 || Math.abs(sf.income - 1.0) > 0.05) {
                    html += `
                        <div class="seasonal-info">
                            <div class="seasonal-label">Сезонные коэффициенты:</div>
                            <div class="seasonal-values">
                                Расходы: ${sf.expenses.toFixed(2)}x | Доходы: ${sf.income.toFixed(2)}x
                            </div>
                        </div>
                    `;
                }
            }
            
            // Рекомендации
            if (forecasts.recommendations && forecasts.recommendations.length > 0) {
                html += `<div class="forecasts-list" style="margin-top: 20px;">`;
                
                forecasts.recommendations.forEach(rec => {
                    const recClass = rec.type === 'critical' ? 'forecast-critical' : 
                                    rec.type === 'warning' ? 'forecast-warning' : 'forecast-info';
                    html += `
                        <div class="forecast-item ${recClass}">
                            <div class="forecast-title">${escapeHtml(rec.title)}</div>
                            <div class="forecast-message">${escapeHtml(rec.message)}</div>
                        </div>
                    `;
                });
                
                html += `</div>`;
            }
            
            html += `</div>`;
        }
        
        if (transactions && transactions.length > 0) {
            html += `
                <h3>Детализация расчёта</h3>
                <table class="transaction-table">
                    <thead>
                        <tr>
                            <th>Показатель</th>
                            <th>Значение</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            
            transactions.forEach(row => {
                const safeIndicator = escapeHtml(row['Показатель'] || '');
                const safeValue = formatNumber(row['Значение'] || 0);
                const currency = row['Показатель']?.includes('Ставка') ? '' : ' ₽';
                html += `
                    <tr>
                        <td>${safeIndicator}</td>
                        <td>${safeValue}${currency}</td>
                    </tr>
                `;
            });
            
            html += `
                    </tbody>
                </table>
            `;
        }
        
        // Добавляем кнопку экспорта
        html += `
            <div style="margin-top: 24px;">
                <button onclick="exportTransactions()" class="btn" style="background: var(--bg-secondary); border: 1px solid var(--border-color);">
                    <span class="btn-text">Экспорт в Excel</span>
                </button>
            </div>
        `;
        
        showResult('transactionResult', html);
        
        // Инициализируем обработчики фильтра категорий после отображения результатов
        setTimeout(() => {
            initTransactionCategoryFilter();
        }, 100);
        
        // Сохраняем результат для экспорта
        window.lastTransactionResult = data;
        window.allTransactions = data.detailed_transactions || [];
        
        console.log('[Debug] Received data:', {
            transactionsCount: data.detailed_transactions?.length || 0,
            hasPlReport: !!data.pl_report,
            hasForecasts: !!data.forecasts,
            hasAnomalies: !!data.anomalies
        });
        
        // Создаем визуализации после отрисовки HTML
        setTimeout(() => {
            try {
                if (data.detailed_transactions && data.detailed_transactions.length > 0) {
                    console.log('[Debug] Creating visualizations for', data.detailed_transactions.length, 'transactions');
                    console.log('[Debug] Sample transaction:', data.detailed_transactions[0]);
                    console.log('[Debug] All transactions:', data.detailed_transactions);
                    
                    // Создаем графики с обработкой ошибок
                    try {
                        createExpensesPieChart(data.detailed_transactions, data.pl_report);
                    } catch (e) {
                        console.error('[Chart] Error creating pie chart:', e);
                    }
                    
                    try {
                        createIncomeExpensesChart(data.detailed_transactions);
                    } catch (e) {
                        console.error('[Chart] Error creating line chart:', e);
                    }
                    
        // Bar chart сравнения периодов
        if (data.period_comparison) {
            try {
                // Сохраняем данные для фильтрации
                window.lastPeriodComparison = data.period_comparison;
                
                // Инициализируем поля дат
                const currentStart = document.getElementById('currentPeriodStart');
                const currentEnd = document.getElementById('currentPeriodEnd');
                if (currentStart && currentEnd && data.period_comparison.current_period) {
                    currentStart.value = data.period_comparison.current_period.start;
                    currentEnd.value = data.period_comparison.current_period.end;
                }
                
                createPeriodComparisonChart(data.period_comparison);
            } catch (e) {
                console.error('[Chart] Error creating period comparison chart:', e);
            }
        }
                    
                    // Waterfall chart для P&L
                    if (data.pl_report) {
                        try {
                            createWaterfallChart(data.pl_report);
                        } catch (e) {
                            console.error('[Chart] Error creating waterfall chart:', e);
                        }
                    }
                    
                    // Отображаем таблицу со всеми транзакциями
                    try {
                        renderTransactionsTable(data.detailed_transactions);
                    } catch (e) {
                        console.error('[Table] Error rendering table:', e);
                    }
                } else {
                    console.warn('[Debug] No detailed_transactions in response. Data keys:', Object.keys(data));
                    console.warn('[Debug] Full data:', data);
                }
            } catch (e) {
                console.error('[Debug] Error in visualization setup:', e);
            }
        }, 300);
        
    } catch (error) {
        console.error('Error:', error);
        const errorMsg = error.message || 'Неизвестная ошибка';
        showResult('transactionResult', 
            `<p class="error-message">❌ Ошибка: ${escapeHtml(errorMsg)}</p>`, true);
    } finally {
        hideLoader(submitButton);
    }
    });
}

// ===== Document Analyzer =====
const documentForm = document.getElementById('documentForm');
if (documentForm) {
    documentForm.addEventListener('submit', async (e) => {
        e.preventDefault();
    
    const form = e.target;
    const submitButton = form.querySelector('button[type="submit"]');
    const fileInput = document.getElementById('documentFile');
    
    if (!fileInput.files[0]) {
        showResult('documentResult', 
            '<p class="error-message">⚠️ Пожалуйста, выберите файл</p>', true);
        return;
    }
    
    showLoader(submitButton);
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    
    try {
        const response = await fetch('/api/analyze-document', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Ошибка при анализе документа');
        }
        
        // Convert markdown to HTML (basic implementation)
        const htmlContent = convertMarkdownToHtml(data.analysis);
        const safeFilename = escapeHtml(data.filename || '');
        
        const html = `
            <h3>📄 Анализ документа: ${safeFilename}</h3>
            <div class="markdown-content">
                ${htmlContent}
            </div>
            <div style="margin-top: 24px;">
                <button onclick="exportDocument()" class="btn" style="background: var(--bg-secondary); border: 1px solid var(--border-color);">
                    <span class="btn-text">Экспорт в Markdown</span>
                </button>
            </div>
        `;
        
        showResult('documentResult', html);
        
        // Сохраняем результат для экспорта
        window.lastDocumentResult = data;
        
    } catch (error) {
        console.error('Error:', error);
        const errorMsg = error.message || 'Неизвестная ошибка';
        showResult('documentResult', 
            `<p class="error-message">❌ Ошибка: ${escapeHtml(errorMsg)}</p>`, true);
    } finally {
        hideLoader(submitButton);
    }
    });
}

// ===== Regulatory Consultant =====
const consultantForm = document.getElementById('consultantForm');
if (consultantForm) {
    consultantForm.addEventListener('submit', async (e) => {
        e.preventDefault();
    
    const form = e.target;
    const submitButton = form.querySelector('button[type="submit"]');
    const questionInput = document.getElementById('question');
    
    const question = questionInput.value.trim();
    
    if (!question) {
        showResult('consultantResult', 
            '<p class="error-message">⚠️ Пожалуйста, введите вопрос</p>', true);
        return;
    }
    
    showLoader(submitButton);
    
    const formData = new FormData();
    formData.append('question', question);
    
    try {
        const response = await fetch('/api/ask-question', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Ошибка при обработке вопроса');
        }
        
        // Convert markdown to HTML
        const htmlContent = convertMarkdownToHtml(data.answer);
        
        const safeQuestion = escapeHtml(data.question || '');
        const html = `
            <h3>💬 Вопрос:</h3>
            <p><strong>${safeQuestion}</strong></p>
            <hr style="margin: 20px 0;">
            <h3>✅ Ответ:</h3>
            <div class="markdown-content">
                ${htmlContent}
            </div>
            <div style="margin-top: 24px;">
                <button onclick="exportConsultant()" class="btn" style="background: var(--bg-secondary); border: 1px solid var(--border-color);">
                    <span class="btn-text">Экспорт в Markdown</span>
                </button>
            </div>
        `;
        
        showResult('consultantResult', html);
        
        // Сохраняем результат для экспорта
        window.lastConsultantResult = data;
        
    } catch (error) {
        console.error('Error:', error);
        const errorMsg = error.message || 'Неизвестная ошибка';
        showResult('consultantResult', 
            `<p class="error-message">❌ Ошибка: ${escapeHtml(errorMsg)}</p>`, true);
    } finally {
        hideLoader(submitButton);
    }
    });
}

// ===== Markdown to HTML Converter =====
function convertMarkdownToHtml(markdown) {
    if (!markdown) return '';
    
    let html = markdown;
    
    // Headers
    html = html.replace(/#### (.+)/g, '<h4>$1</h4>');
    html = html.replace(/### (.+)/g, '<h3>$1</h3>');
    html = html.replace(/## (.+)/g, '<h3>$1</h3>');
    
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    
    // Lists (simple conversion)
    const lines = html.split('\n');
    let inList = false;
    let result = [];
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        // Check if line is a list item
        if (line.trim().match(/^[-*]\s+/)) {
            if (!inList) {
                result.push('<ul>');
                inList = true;
            }
            const listItem = line.trim().replace(/^[-*]\s+/, '');
            result.push(`<li>${listItem}</li>`);
        } else {
            if (inList) {
                result.push('</ul>');
                inList = false;
            }
            
            // Horizontal rules
            if (line.trim() === '---') {
                result.push('<hr>');
            } else if (line.trim()) {
                result.push(`<p>${line}</p>`);
            } else {
                result.push('<br>');
            }
        }
    }
    
    if (inList) {
        result.push('</ul>');
    }
    
    return result.join('\n');
}

// ===== Export Functions (глобальные для onclick) =====
window.exportTransactions = async function() {
    if (!window.lastTransactionResult) {
        alert('Нет результатов для экспорта');
        return;
    }
    
    try {
        console.log('[Export] Starting export');
        const formData = new FormData();
        formData.append('result_data', JSON.stringify(window.lastTransactionResult));
        formData.append('format', 'excel');
        
        const endpoint = '/api/export/transactions';
        
        console.log('[Export] Endpoint:', endpoint);
        const response = await fetch(endpoint, {
            method: 'POST',
            body: formData
        });
        
        console.log('[Export] Response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('[Export] Error response:', errorText);
            throw new Error(`Ошибка экспорта: ${response.status} - ${errorText}`);
        }
        
        const blob = await response.blob();
        console.log('[Export] Blob size:', blob.size, 'type:', blob.type);
        
        if (blob.size === 0) {
            throw new Error('Получен пустой файл');
        }
        
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `transactions_${new Date().toISOString().slice(0,10)}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        console.log('[Export] Export completed successfully');
    } catch (error) {
        console.error('[Export] Export error:', error);
        alert(`Ошибка экспорта: ${error.message}`);
    }
}

window.exportDocument = async function() {
    if (!window.lastDocumentResult) {
        alert('Нет результатов для экспорта');
        return;
    }
    
    try {
        const formData = new FormData();
        formData.append('result_data', JSON.stringify(window.lastDocumentResult));
        
        const response = await fetch('/api/export/document', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error('Ошибка экспорта');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `document_${new Date().toISOString().slice(0,10)}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (error) {
        alert(`Ошибка экспорта: ${error.message}`);
    }
}

window.exportConsultant = async function() {
    if (!window.lastConsultantResult) {
        alert('Нет результатов для экспорта');
        return;
    }
    
    try {
        const formData = new FormData();
        formData.append('result_data', JSON.stringify(window.lastConsultantResult));
        
        const response = await fetch('/api/export/consultant', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error('Ошибка экспорта');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `consultant_${new Date().toISOString().slice(0,10)}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (error) {
        alert(`Ошибка экспорта: ${error.message}`);
    }
}

// ===== History Management =====
function getHistoryFilter() {
    const selected = document.querySelector('input[name="historyFilter"]:checked');
    return selected ? selected.value : '';
}

async function loadHistory() {
    const filter = getHistoryFilter();
    const resultDiv = document.getElementById('historyResult');
    const button = document.getElementById('loadHistoryBtn');
    
    showLoader(button);
    
    try {
        const url = `/api/history?limit=50${filter ? `&service_type=${filter}` : ''}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Ошибка загрузки истории');
        }
        
        const history = data.history || [];
        
        // Сохраняем историю в глобальную переменную для доступа из модального окна
        currentHistory = history.slice().reverse();
        
        if (history.length === 0) {
            resultDiv.innerHTML = '<p>История пуста</p>';
            resultDiv.classList.remove('hidden');
            return;
        }
        
        let html = `
            <h3>История запросов (${history.length})</h3>
            <div class="history-list">
        `;
        
        history.reverse().forEach((entry, index) => {
            const timestamp = new Date(entry.timestamp).toLocaleString('ru-RU');
            const serviceType = entry.service_type;
            const serviceNames = {
                'transactions': 'Анализ транзакций',
                'documents': 'Анализ документов',
                'consultant': 'Юридический консультант'
            };
            
            html += `
                <div class="history-item">
                    <div class="history-header">
                        <span class="history-service">${serviceNames[serviceType] || serviceType}</span>
                        <span class="history-time">${timestamp}</span>
                    </div>
                    <div class="history-content">
                        ${formatHistoryEntry(entry, index)}
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
        resultDiv.innerHTML = html;
        resultDiv.classList.remove('hidden');
        
    } catch (error) {
        resultDiv.innerHTML = `<p class="error-message">Ошибка: ${escapeHtml(error.message)}</p>`;
        resultDiv.classList.remove('hidden');
    } finally {
        hideLoader(button);
    }
}

function formatHistoryEntry(entry, index) {
    const input = entry.input || {};
    const result = entry.result || {};
    
    if (entry.service_type === 'consultant') {
        const answer = result.answer || '';
        const isLong = answer.length > 200;
        const preview = isLong ? answer.substring(0, 200) + '...' : answer;
        return `
            <div><strong>Вопрос:</strong> ${escapeHtml(input.question || '')}</div>
            <div style="margin-top: 8px;"><strong>Ответ:</strong> ${isLong ? convertMarkdownToHtml(preview) : convertMarkdownToHtml(answer)}</div>
            ${isLong ? `<button onclick="showFullAnswer(${index}, 'consultant')" class="btn-show-full" style="margin-top: 12px;">Показать полностью</button>` : ''}
        `;
    } else if (entry.service_type === 'transactions') {
        const summary = result.summary || {};
        const hasFullData = result.detailed_transactions || result.pl_report || result.anomalies || result.forecasts;
        return `
            <div><strong>Файл:</strong> ${escapeHtml(input.filename || '')}</div>
            <div><strong>Режим:</strong> ${escapeHtml(formatTaxMode(input.tax_mode || ''))}</div>
            <div><strong>Налог:</strong> ${formatNumber(summary.tax || 0)} ₽</div>
            ${hasFullData ? `<button onclick="showFullAnswer(${index}, 'transactions')" class="btn-show-full" style="margin-top: 12px;">Показать полный отчет</button>` : ''}
        `;
    } else if (entry.service_type === 'documents') {
        const analysis = result.analysis || '';
        const isLong = analysis.length > 200;
        const preview = isLong ? analysis.substring(0, 200) + '...' : analysis;
        return `
            <div><strong>Файл:</strong> ${escapeHtml(input.filename || '')}</div>
            <div style="margin-top: 8px;" class="markdown-content">${convertMarkdownToHtml(preview)}</div>
            ${isLong ? `<button onclick="showFullAnswer(${index}, 'documents')" class="btn-show-full" style="margin-top: 12px;">Показать полностью</button>` : ''}
        `;
    }
    
    return '<div>Данные недоступны</div>';
}

// Глобальная переменная для хранения истории
let currentHistory = [];

async function showFullAnswer(index, serviceType) {
    // Сохраняем историю в глобальную переменную при загрузке
    if (currentHistory.length === 0) {
        const filter = getHistoryFilter();
        const url = `/api/history?limit=50${filter ? `&service_type=${filter}` : ''}`;
        const response = await fetch(url);
        const data = await response.json();
        currentHistory = (data.history || []).reverse();
    }
    
    const entry = currentHistory[index];
    if (!entry) return;
    
    const input = entry.input || {};
    const result = entry.result || {};
    
    let title = '';
    let content = '';
    
    if (serviceType === 'consultant') {
        title = `Вопрос: ${escapeHtml(input.question || '')}`;
        content = convertMarkdownToHtml(result.answer || '');
    } else if (serviceType === 'transactions') {
        title = `Анализ транзакций: ${escapeHtml(input.filename || '')}`;
        content = formatFullTransactionResult(result);
    } else if (serviceType === 'documents') {
        title = `Анализ документа: ${escapeHtml(input.filename || '')}`;
        content = convertMarkdownToHtml(result.analysis || '');
    }
    
    // Создаем модальное окно
    const modal = document.createElement('div');
    modal.className = 'history-modal';
    modal.innerHTML = `
        <div class="history-modal-content">
            <div class="history-modal-header">
                <h3>${title}</h3>
                <button class="history-modal-close" onclick="closeHistoryModal()">&times;</button>
            </div>
            <div class="history-modal-body">
                ${content}
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Закрытие по клику вне модального окна
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeHistoryModal();
        }
    });
    
    // Закрытие по Escape
    const escapeHandler = function(e) {
        if (e.key === 'Escape') {
            closeHistoryModal();
            document.removeEventListener('keydown', escapeHandler);
        }
    };
    document.addEventListener('keydown', escapeHandler);
}

function closeHistoryModal() {
    const modal = document.querySelector('.history-modal');
    if (modal) {
        modal.remove();
    }
}

function formatFullTransactionResult(result) {
    let html = '';
    
    if (result.summary) {
        const s = result.summary;
        html += `
            <div class="summary-section">
                <h4>Сводка</h4>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 16px;">
                    <div>
                        <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Налог</div>
                        <div style="font-size: 20px; font-weight: 600; color: var(--text-primary);">${formatNumber(s.tax || 0)} ₽</div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Доходы</div>
                        <div style="font-size: 20px; font-weight: 600; color: var(--text-primary);">${formatNumber(s.income || 0)} ₽</div>
                    </div>
                    <div>
                        <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Расходы</div>
                        <div style="font-size: 20px; font-weight: 600; color: var(--text-primary);">${formatNumber(s.expenses || 0)} ₽</div>
                    </div>
                </div>
            </div>
        `;
    }
    
    if (result.pl_report && result.pl_report.length > 0) {
        html += `<div class="summary-section"><h4>Отчет о прибылях и убытках</h4>${formatPLReport(result.pl_report)}</div>`;
    }
    
    if (result.anomalies && result.anomalies.length > 0) {
        html += `<div class="summary-section"><h4>Обнаруженные аномалии</h4><div class="anomalies-list">${formatAnomalies(result.anomalies)}</div></div>`;
    }
    
    if (result.forecasts && result.forecasts.length > 0) {
        html += `<div class="summary-section"><h4>Прогнозы</h4><div class="forecasts-list">${formatForecasts(result.forecasts)}</div></div>`;
    }
    
    return html;
}

function formatPLReport(pl) {
    let html = '<div class="pl-report">';
    pl.forEach(item => {
        const isHighlight = item.label && (item.label.includes('Прибыль') || item.label.includes('EBITDA'));
        html += `
            <div class="pl-row ${isHighlight ? 'pl-highlight' : ''}">
                <span class="pl-label">${escapeHtml(item.label || '')}</span>
                <span class="pl-value">${formatNumber(item.value || 0)} ₽</span>
            </div>
        `;
    });
    html += '</div>';
    return html;
}

function formatAnomalies(anomalies) {
    return anomalies.map(a => {
        const severityClass = a.severity === 'high' ? 'anomaly-high' : 'anomaly-medium';
        return `
            <div class="anomaly-item ${severityClass}">
                <div class="anomaly-type">${escapeHtml(a.type || '')}</div>
                <div class="anomaly-description">${escapeHtml(a.description || '')}</div>
            </div>
        `;
    }).join('');
}

function formatForecasts(forecasts) {
    return forecasts.map(f => {
        const typeClass = f.type === 'critical' ? 'forecast-critical' : 
                         f.type === 'warning' ? 'forecast-warning' : 'forecast-info';
        return `
            <div class="forecast-item ${typeClass}">
                <div class="forecast-type">${escapeHtml(f.period || '')}</div>
                <div class="forecast-description">${escapeHtml(f.description || '')}</div>
                ${f.recommendations ? `<div class="forecast-recommendations" style="margin-top: 8px; font-size: 13px;">${escapeHtml(f.recommendations)}</div>` : ''}
            </div>
        `;
    }).join('');
}

async function exportHistory() {
    const filter = getHistoryFilter();
    
    try {
        const url = `/api/export/history?format=excel${filter ? `&service_type=${filter}` : ''}`;
        const response = await fetch(url);
        
        if (!response.ok) throw new Error('Ошибка экспорта');
        
        const blob = await response.blob();
        const url_obj = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url_obj;
        a.download = `history_${new Date().toISOString().slice(0,10)}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url_obj);
    } catch (error) {
        alert(`Ошибка экспорта: ${error.message}`);
    }
}

async function clearHistory() {
    if (!confirm('Вы уверены, что хотите очистить всю историю?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/history', {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error('Ошибка очистки');
        
        document.getElementById('historyResult').innerHTML = '<p>История очищена</p>';
        document.getElementById('historyResult').classList.remove('hidden');
    } catch (error) {
        alert(`Ошибка: ${error.message}`);
    }
}

// Event listeners для истории
document.getElementById('loadHistoryBtn')?.addEventListener('click', loadHistory);
document.getElementById('exportHistoryBtn')?.addEventListener('click', exportHistory);
document.getElementById('clearHistoryBtn')?.addEventListener('click', clearHistory);

// Обработчики для dropdown фильтра истории
const historyFilterTrigger = document.getElementById('historyFilterTrigger');
const historyFilterMenu = document.getElementById('historyFilterMenu');

// Открытие/закрытие меню
if (historyFilterTrigger && historyFilterMenu) {
    historyFilterTrigger.addEventListener('click', function(e) {
        e.stopPropagation();
        const isOpen = historyFilterMenu.classList.contains('open');
        
        if (isOpen) {
            historyFilterMenu.classList.remove('open');
            historyFilterTrigger.classList.remove('active');
        } else {
            historyFilterMenu.classList.add('open');
            historyFilterTrigger.classList.add('active');
        }
    });
    
    // Закрытие меню при клике вне его
    document.addEventListener('click', function(e) {
        if (!historyFilterTrigger.contains(e.target) && !historyFilterMenu.contains(e.target)) {
            historyFilterMenu.classList.remove('open');
            historyFilterTrigger.classList.remove('active');
        }
    });
    
    // Обработчики для radio buttons
    document.querySelectorAll('input[name="historyFilter"]').forEach(radio => {
        radio.addEventListener('change', function() {
            const label = document.querySelector(`label[for="${this.id}"]`);
            if (label) {
                const labelText = label.getAttribute('data-label') || label.textContent.trim();
                const triggerText = document.querySelector('.filter-trigger-text');
                if (triggerText) {
                    triggerText.textContent = labelText;
                }
                
                // Закрываем меню после выбора
                historyFilterMenu.classList.remove('open');
                historyFilterTrigger.classList.remove('active');
            }
        });
    });
}

// Функция для инициализации обработчиков фильтра категорий транзакций
function initTransactionCategoryFilter() {
    const transactionCategoryFilterTrigger = document.getElementById('transactionCategoryFilterTrigger');
    const transactionCategoryFilterMenu = document.getElementById('transactionCategoryFilterMenu');
    
    if (!transactionCategoryFilterTrigger || !transactionCategoryFilterMenu) {
        return; // Элементы еще не созданы
    }
    
    // Удаляем старые обработчики, если они есть
    const newTrigger = transactionCategoryFilterTrigger.cloneNode(true);
    transactionCategoryFilterTrigger.parentNode.replaceChild(newTrigger, transactionCategoryFilterTrigger);
    
    const newMenu = transactionCategoryFilterMenu.cloneNode(true);
    transactionCategoryFilterMenu.parentNode.replaceChild(newMenu, transactionCategoryFilterMenu);
    
    // Добавляем обработчики на новые элементы
    newTrigger.addEventListener('click', function(e) {
        e.stopPropagation();
        const isOpen = newMenu.classList.contains('open');
        
        if (isOpen) {
            newMenu.classList.remove('open');
            newTrigger.classList.remove('active');
        } else {
            newMenu.classList.add('open');
            newTrigger.classList.add('active');
        }
    });
    
    // Закрытие меню при клике вне его
    document.addEventListener('click', function(e) {
        if (newTrigger && newMenu && 
            !newTrigger.contains(e.target) && !newMenu.contains(e.target)) {
            newMenu.classList.remove('open');
            newTrigger.classList.remove('active');
        }
    });
    
    // Обработчики для radio buttons
    document.querySelectorAll('input[name="transactionCategoryFilter"]').forEach(radio => {
        radio.addEventListener('change', function() {
            const label = document.querySelector(`label[for="${this.id}"]`);
            if (label) {
                const labelText = label.getAttribute('data-label') || label.textContent.trim();
                newTrigger.querySelector('.filter-trigger-text').textContent = labelText;
            }
            newMenu.classList.remove('open');
            newTrigger.classList.remove('active');
            // НЕ применяем фильтр автоматически - пользователь должен нажать "Применить фильтры"
        });
    });
}

// ===== Health Check on Load =====
window.addEventListener('load', async () => {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        console.log('✅ API Health Check:', data);
    } catch (error) {
        console.error('❌ API Health Check Failed:', error);
    }
    
    // Инициализация текста триггера фильтра истории
    const checkedRadio = document.querySelector('input[name="historyFilter"]:checked');
    if (checkedRadio) {
        const label = document.querySelector(`label[for="${checkedRadio.id}"]`);
        if (label) {
            const labelText = label.getAttribute('data-label') || label.textContent.trim();
            const triggerText = document.querySelector('.filter-trigger-text');
            if (triggerText) {
                triggerText.textContent = labelText;
            }
        }
    }
});

// ===== Визуализации для Transaction Analyzer =====

function createExpensesPieChart(transactions, plReport) {
    // Проверяем, что Chart.js загружен
    if (typeof Chart === 'undefined') {
        console.error('[Chart] Chart.js library not loaded!');
        const ctx = document.getElementById('expensesPieChart');
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<p style="color: var(--text-danger); padding: 20px; text-align: center;">Ошибка: библиотека Chart.js не загружена</p>';
        }
        return;
    }
    
    const ctx = document.getElementById('expensesPieChart');
    if (!ctx) {
        console.warn('[Chart] Canvas element not found for pie chart');
        return;
    }
    
    // Уничтожаем предыдущий график, если есть
    if (window.expensesChart) {
        try {
            window.expensesChart.destroy();
        } catch (e) {
            console.warn('[Chart] Error destroying previous pie chart:', e);
        }
    }
    
    // Группируем расходы по категориям (исключаем доходы)
    const expensesByCategory = {};
    transactions.forEach(t => {
        if (t.Категория && t.Категория !== 'Поступление от клиента') {
            const amount = Math.abs(parseFloat(t.Сумма) || 0);
            expensesByCategory[t.Категория] = (expensesByCategory[t.Категория] || 0) + amount;
        }
    });
    
    const labels = Object.keys(expensesByCategory);
    const data = Object.values(expensesByCategory);
    
    // Цвета для категорий
    const colors = [
        'rgba(99, 102, 241, 0.8)',  // indigo
        'rgba(236, 72, 153, 0.8)',  // pink
        'rgba(34, 197, 94, 0.8)',   // green
        'rgba(251, 146, 60, 0.8)',  // orange
        'rgba(59, 130, 246, 0.8)',  // blue
        'rgba(168, 85, 247, 0.8)',  // purple
        'rgba(239, 68, 68, 0.8)',  // red
        'rgba(20, 184, 166, 0.8)',  // teal
    ];
    
    window.expensesChart = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors.slice(0, labels.length),
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        padding: 15,
                        font: {
                            size: 12
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = formatNumber(context.parsed);
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((context.parsed / total) * 100).toFixed(1);
                            return `${label}: ${value} ₽ (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

function createIncomeExpensesChart(transactions) {
    // Проверяем, что Chart.js загружен
    if (typeof Chart === 'undefined') {
        console.error('[Chart] Chart.js library not loaded!');
        const ctx = document.getElementById('incomeExpensesChart');
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<p style="color: var(--text-danger); padding: 20px; text-align: center;">Ошибка: библиотека Chart.js не загружена</p>';
        }
        return;
    }
    
    const ctx = document.getElementById('incomeExpensesChart');
    if (!ctx) {
        console.warn('[Chart] Canvas element not found for income/expenses chart');
        return;
    }
    
    // Уничтожаем предыдущий график, если есть
    if (window.incomeExpensesChart) {
        try {
            window.incomeExpensesChart.destroy();
        } catch (e) {
            console.warn('[Chart] Error destroying previous chart:', e);
        }
    }
    
    if (!transactions || transactions.length === 0) {
        console.warn('[Chart] No transactions data for income/expenses chart');
        // Показываем сообщение вместо пустого графика
        ctx.parentElement.innerHTML = '<p style="color: var(--text-secondary); padding: 20px; text-align: center;">Недостаточно данных для построения графика</p>';
        return;
    }
    
    console.log('[Chart] Processing', transactions.length, 'transactions for income/expenses chart');
    
    // Группируем по датам
    const byDate = {};
    let processedCount = 0;
    transactions.forEach(t => {
        if (!t.Дата) {
            console.warn('[Chart] Transaction without date:', t);
            return;
        }
        
        // Обрабатываем разные форматы дат
        let dateStr = String(t.Дата);
        if (dateStr.includes('T')) {
            dateStr = dateStr.split('T')[0];
        }
        // Если дата в формате "YYYY-MM-DD", используем как есть
        const dateMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (!dateMatch) {
            console.warn('[Chart] Invalid date format:', t.Дата, 'from transaction:', t);
            return;
        }
        
        const date = dateMatch[0]; // "YYYY-MM-DD"
        if (!byDate[date]) {
            byDate[date] = { income: 0, expenses: 0 };
        }
        const amount = parseFloat(t.Сумма) || 0;
        if (t.Категория === 'Поступление от клиента') {
            byDate[date].income += amount;
        } else {
            byDate[date].expenses += Math.abs(amount);
        }
        processedCount++;
    });
    
    console.log('[Chart] Processed', processedCount, 'transactions, found', Object.keys(byDate).length, 'unique dates');
    
    // Сортируем по дате
    const sortedDates = Object.keys(byDate).sort();
    
    if (sortedDates.length === 0) {
        console.warn('[Chart] No valid dates found after processing');
        ctx.parentElement.innerHTML = '<p style="color: var(--text-secondary); padding: 20px; text-align: center;">Не удалось обработать даты транзакций</p>';
        return;
    }
    
    const incomeData = sortedDates.map(date => byDate[date].income);
    const expensesData = sortedDates.map(date => byDate[date].expenses);
    
    console.log('[Chart] Creating income/expenses chart with', sortedDates.length, 'dates');
    console.log('[Chart] Date range:', sortedDates[0], 'to', sortedDates[sortedDates.length - 1]);
    
    try {
        window.incomeExpensesChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: sortedDates.map(date => {
                const d = new Date(date + 'T00:00:00');
                if (isNaN(d.getTime())) {
                    return date;
                }
                // Формат дд.мм.гг
                return formatDate(date);
            }),
            datasets: [
                {
                    label: 'Доходы',
                    data: incomeData,
                    borderColor: 'rgba(34, 197, 94, 1)',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: 'rgba(34, 197, 94, 1)',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2
                },
                {
                    label: 'Расходы',
                    data: expensesData,
                    borderColor: 'rgba(239, 68, 68, 1)',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: 'rgba(239, 68, 68, 1)',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    enabled: true,
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${formatNumber(context.parsed.y)} ₽`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return formatNumber(value) + ' ₽';
                        }
                    }
                }
            },
            elements: {
                point: {
                    radius: 4,
                    hoverRadius: 8,
                    hoverBorderWidth: 3
                },
                line: {
                    tension: 0.4
                }
            }
        }
    });
    } catch (e) {
        console.error('[Chart] Error creating Chart.js instance:', e);
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<p style="color: var(--text-danger); padding: 20px; text-align: center;">Ошибка при создании графика: ' + escapeHtml(e.message) + '</p>';
        }
    }
}

function createPeriodComparisonChart(periodComparison) {
    if (typeof Chart === 'undefined') {
        console.error('[Chart] Chart.js library not loaded!');
        return;
    }
    
    const ctx = document.getElementById('periodComparisonChart');
    if (!ctx) {
        console.warn('[Chart] Canvas element not found for period comparison chart');
        return;
    }
    
    // Показываем wrapper
    const wrapper = document.getElementById('periodComparisonChartWrapper');
    if (wrapper) {
        wrapper.style.display = 'block';
    }
    
    // Уничтожаем предыдущий график
    if (window.periodComparisonChart) {
        try {
            window.periodComparisonChart.destroy();
        } catch (e) {
            console.warn('[Chart] Error destroying previous period comparison chart:', e);
        }
    }
    
    const current = periodComparison.current_period;
    const previous = periodComparison.previous_period;
    const comparison = periodComparison.comparison || {};
    
    // Показываем информацию о периодах
    const infoDiv = document.getElementById('periodComparisonInfo');
    if (infoDiv) {
        const currentLabel = `Текущий: ${formatDate(current.start)} - ${formatDate(current.end)}`;
        const previousLabel = `Предыдущий: ${formatDate(previous.start)} - ${formatDate(previous.end)}`;
        const incomeChange = comparison.income_change_pct ? 
            ` (${comparison.income_change_pct > 0 ? '+' : ''}${comparison.income_change_pct.toFixed(1)}%)` : '';
        const expensesChange = comparison.expenses_change_pct ? 
            ` (${comparison.expenses_change_pct > 0 ? '+' : ''}${comparison.expenses_change_pct.toFixed(1)}%)` : '';
        
        infoDiv.innerHTML = `
            <div style="font-size: 13px; font-weight: 400; line-height: 1.6; color: var(--text-primary);">
                <div style="margin-bottom: 4px;">${currentLabel}</div>
                <div style="margin-bottom: 4px;">${previousLabel}</div>
                <div>Изменение: Доходы${incomeChange} | Расходы${expensesChange}</div>
            </div>
        `;
    }
    
    try {
        window.periodComparisonChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['Доходы', 'Расходы', 'Баланс'],
                datasets: [
                    {
                        label: 'Текущий период',
                        data: [current.income, current.expenses, current.balance],
                        backgroundColor: 'rgba(99, 102, 241, 0.8)',
                        borderColor: 'rgba(99, 102, 241, 1)',
                        borderWidth: 2
                    },
                    {
                        label: 'Предыдущий период',
                        data: [previous.income, previous.expenses, previous.balance],
                        backgroundColor: 'rgba(156, 163, 175, 0.8)',
                        borderColor: 'rgba(156, 163, 175, 1)',
                        borderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${formatNumber(context.parsed.y)} ₽`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        ticks: {
                            callback: function(value) {
                                return formatNumber(value) + ' ₽';
                            }
                        }
                    }
                }
            }
        });
    } catch (e) {
        console.error('[Chart] Error creating period comparison chart:', e);
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<p style="color: var(--text-danger); padding: 20px; text-align: center;">Ошибка при создании графика</p>';
        }
    }
}

function createWaterfallChart(plReport) {
    if (typeof Chart === 'undefined') {
        console.error('[Chart] Chart.js library not loaded!');
        return;
    }
    
    const ctx = document.getElementById('waterfallChart');
    if (!ctx) {
        console.warn('[Chart] Canvas element not found for waterfall chart');
        return;
    }
    
    // Показываем wrapper
    const wrapper = document.getElementById('waterfallChartWrapper');
    if (wrapper) {
        wrapper.style.display = 'block';
    }
    
    // Уничтожаем предыдущий график
    if (window.waterfallChart) {
        try {
            window.waterfallChart.destroy();
        } catch (e) {
            console.warn('[Chart] Error destroying previous waterfall chart:', e);
        }
    }
    
    // Waterfall: Выручка → COGS → Валовая прибыль → Операционные расходы → EBITDA
    const revenue = plReport.revenue || 0;
    const cogs = plReport.cogs || 0;
    const grossProfit = plReport.gross_profit || 0;
    const operatingExpenses = plReport.operating_expenses || 0;
    const operatingProfit = plReport.operating_profit || 0;
    
    const data = [
        revenue,            // Выручка
        -cogs,              // COGS (отрицательное значение)
        grossProfit,        // Валовая прибыль
        -operatingExpenses, // Операционные расходы
        operatingProfit     // EBITDA
    ];
    
    const labels = ['Выручка', 'COGS', 'Валовая прибыль', 'Операционные расходы', 'EBITDA'];
    const colors = [
        'rgba(34, 197, 94, 0.8)',   // Выручка - зеленый
        'rgba(239, 68, 68, 0.8)',   // COGS - красный
        'rgba(34, 197, 94, 0.8)',   // Валовая прибыль - зеленый
        'rgba(239, 68, 68, 0.8)',   // Операционные расходы - красный
        'rgba(99, 102, 241, 0.8)'   // EBITDA - синий
    ];
    
    try {
        // Используем bar chart для waterfall
        window.waterfallChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'P&L',
                    data: data,
                    backgroundColor: colors,
                    borderColor: colors.map(c => c.replace('0.8', '1')),
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const value = context.parsed.y;
                                const sign = value >= 0 ? '+' : '';
                                return `${context.label}: ${sign}${formatNumber(value)} ₽`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        ticks: {
                            callback: function(value) {
                                return formatNumber(value) + ' ₽';
                            }
                        }
                    }
                }
            }
        });
    } catch (e) {
        console.error('[Chart] Error creating waterfall chart:', e);
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<p style="color: var(--text-danger); padding: 20px; text-align: center;">Ошибка при создании графика</p>';
        }
    }
}

function renderTransactionsTable(transactions, filtered = false) {
    const container = document.getElementById('filteredTransactionsTable');
    if (!container) {
        console.warn('[Table] Container not found');
        return;
    }
    
    if (!transactions || transactions.length === 0) {
        container.innerHTML = '<p style="color: var(--text-secondary); padding: 20px; text-align: center;">Транзакции не найдены</p>';
        return;
    }
    
    console.log('[Table] Rendering', transactions.length, 'transactions');
    console.log('[Table] First 3 transactions:', transactions.slice(0, 3));
    
    // Проверяем, что все транзакции имеют необходимые поля
    const validTransactions = transactions.filter(t => {
        const hasRequiredFields = t.Дата !== undefined && t.Сумма !== undefined;
        if (!hasRequiredFields) {
            console.warn('[Table] Transaction missing required fields:', t);
        }
        return hasRequiredFields;
    });
    
    console.log('[Table] Valid transactions:', validTransactions.length, 'out of', transactions.length);
    
    if (validTransactions.length === 0) {
        container.innerHTML = '<p style="color: var(--text-secondary); padding: 20px; text-align: center;">Нет валидных транзакций для отображения</p>';
        return;
    }
    
    let html = `
        <div style="overflow-x: auto;">
            <table class="transaction-table" style="width: 100%; margin-top: 16px;">
                <thead>
                    <tr>
                        <th>Дата</th>
                        <th>Категория</th>
                        <th>Подкатегория</th>
                        <th>Контрагент</th>
                        <th>Назначение</th>
                        <th style="text-align: right;">Сумма</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    validTransactions.forEach((t, index) => {
        const amount = parseFloat(t.Сумма) || 0;
        const isIncome = t.Категория === 'Поступление от клиента';
        const amountClass = isIncome ? 'text-success' : 'text-danger';
        const amountSign = isIncome ? '+' : '-';
        
        // Проверяем дату
        let dateDisplay = formatDate(t.Дата || '');
        
        // Назначение платежа - делаем кликабельным для просмотра полного текста
        const purposeRaw = t['Назначение платежа'] || '—';
        const purposeText = escapeHtml(purposeRaw);
        const purposeId = `purpose-${index}`;
        const purposeLength = purposeRaw.length;
        const needsButton = purposeLength > 40; // Уменьшил порог, чтобы кнопка появлялась чаще
        
        html += `
            <tr>
                <td>${dateDisplay}</td>
                <td>${escapeHtml(t.Категория || '—')}</td>
                <td>${escapeHtml(t.Подкатегория || '—')}</td>
                <td>${escapeHtml(t.Контрагент || '—')}</td>
                <td style="max-width: 400px; position: relative;">
                    <div style="display: flex; align-items: flex-start; gap: 8px; flex-wrap: nowrap;">
                        <span id="${purposeId}" data-full-text="${purposeText}" style="flex: 1; min-width: 0; display: inline-block; max-width: ${needsButton ? '280px' : '100%'}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${purposeText}</span>
                        ${needsButton ? `<button onclick="togglePurposeText('${purposeId}')" style="flex-shrink: 0; padding: 4px 8px; font-size: 11px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 4px; cursor: pointer; white-space: nowrap;">Показать полностью</button>` : ''}
                    </div>
                </td>
                <td style="text-align: right; font-weight: 600;" class="${amountClass}">${amountSign}${formatNumber(Math.abs(amount))} ₽</td>
            </tr>
        `;
    });
    
    html += `
                </tbody>
            </table>
            <p style="color: var(--text-secondary); margin-top: 12px; font-size: 14px;">Всего транзакций: ${validTransactions.length}${validTransactions.length !== transactions.length ? ` (из ${transactions.length} полученных)` : ''}</p>
        </div>
    `;
    
    container.innerHTML = html;
    console.log('[Table] Table rendered successfully with', validTransactions.length, 'rows');
}

function applyFilters() {
    // Получаем выбранную категорию из radio button
    const selectedCategoryRadio = document.querySelector('input[name="transactionCategoryFilter"]:checked');
    const categoryFilter = selectedCategoryRadio ? selectedCategoryRadio.value : '';
    
    if (!window.allTransactions || window.allTransactions.length === 0) {
        console.warn('[Filters] No transactions available');
        return;
    }
    
    console.log('[Filters] Applying filters to', window.allTransactions.length, 'transactions');
    
    // categoryFilter уже получен выше из radio button
    const dateFrom = document.getElementById('dateFromFilter')?.value || '';
    const dateTo = document.getElementById('dateToFilter')?.value || '';
    
    console.log('[Filters] Filter values:', { categoryFilter, dateFrom, dateTo });
    
    let filtered = [...window.allTransactions];
    
    // Фильтр по категории
    if (categoryFilter) {
        const beforeCount = filtered.length;
        filtered = filtered.filter(t => {
            const matches = t.Категория === categoryFilter;
            if (!matches) {
                console.log('[Filters] Category filter: excluded', t.Категория, 'expected', categoryFilter);
            }
            return matches;
        });
        console.log('[Filters] Category filter:', beforeCount, '->', filtered.length);
    }
    
    // Фильтр по датам
    if (dateFrom) {
        const beforeCount = filtered.length;
        filtered = filtered.filter(t => {
            if (!t.Дата) {
                console.warn('[Filters] Transaction without date:', t);
                return false;
            }
            
            // Парсим дату из транзакции (может быть в формате "YYYY-MM-DD" или "YYYY-MM-DDTHH:mm:ss")
            let txDateStr = String(t.Дата);
            if (txDateStr.includes('T')) {
                txDateStr = txDateStr.split('T')[0];
            }
            
            const txDate = new Date(txDateStr + 'T00:00:00');
            const fromDate = new Date(dateFrom + 'T00:00:00');
            
            if (isNaN(txDate.getTime())) {
                console.warn('[Filters] Invalid transaction date:', t.Дата);
                return false;
            }
            
            // Сравниваем только даты (без времени)
            txDate.setHours(0, 0, 0, 0);
            fromDate.setHours(0, 0, 0, 0);
            
            const matches = txDate >= fromDate;
            if (!matches) {
                console.log('[Filters] DateFrom filter: excluded', txDateStr, 'expected >=', dateFrom);
            }
            return matches;
        });
        console.log('[Filters] DateFrom filter:', beforeCount, '->', filtered.length);
    }
    
    if (dateTo) {
        const beforeCount = filtered.length;
        filtered = filtered.filter(t => {
            if (!t.Дата) {
                return false;
            }
            
            // Парсим дату из транзакции
            let txDateStr = String(t.Дата);
            if (txDateStr.includes('T')) {
                txDateStr = txDateStr.split('T')[0];
            }
            
            const txDate = new Date(txDateStr + 'T00:00:00');
            const toDate = new Date(dateTo + 'T23:59:59'); // Включаем весь день
            
            if (isNaN(txDate.getTime())) {
                console.warn('[Filters] Invalid transaction date:', t.Дата);
                return false;
            }
            
            // Сравниваем только даты (без времени)
            txDate.setHours(0, 0, 0, 0);
            toDate.setHours(23, 59, 59, 999);
            
            const matches = txDate <= toDate;
            if (!matches) {
                console.log('[Filters] DateTo filter: excluded', txDateStr, 'expected <=', dateTo);
            }
            return matches;
        });
        console.log('[Filters] DateTo filter:', beforeCount, '->', filtered.length);
    }
    
    console.log('[Filters] Final filtered count:', filtered.length, 'out of', window.allTransactions.length);
    renderTransactionsTable(filtered, true);
}

function resetFilters() {
    console.log('[Filters] Resetting filters');
    
    // Сбрасываем категорию через radio button
    const allCategoryRadio = document.getElementById('tx-filter-all');
    if (allCategoryRadio) {
        allCategoryRadio.checked = true;
        const trigger = document.getElementById('transactionCategoryFilterTrigger');
        if (trigger) {
            trigger.querySelector('.filter-trigger-text').textContent = 'Все категории';
        }
    }
    
    const dateFromFilter = document.getElementById('dateFromFilter');
    const dateToFilter = document.getElementById('dateToFilter');
    
    if (dateFromFilter) dateFromFilter.value = '';
    if (dateToFilter) dateToFilter.value = '';
    
    if (window.allTransactions && window.allTransactions.length > 0) {
        console.log('[Filters] Showing all', window.allTransactions.length, 'transactions');
        renderTransactionsTable(window.allTransactions);
    } else {
        console.warn('[Filters] No transactions to show');
    }
}

// ===== Period Comparison Filters =====
window.updatePeriodComparison = async function() {
    const currentStart = document.getElementById('currentPeriodStart')?.value;
    const currentEnd = document.getElementById('currentPeriodEnd')?.value;
    const previousStart = document.getElementById('previousPeriodStart')?.value;
    const previousEnd = document.getElementById('previousPeriodEnd')?.value;
    
    if (!currentStart || !currentEnd) {
        alert('Пожалуйста, укажите текущий период');
        return;
    }
    
    try {
        let url = `/api/period-comparison?current_start=${currentStart}&current_end=${currentEnd}`;
        if (previousStart && previousEnd) {
            url += `&previous_start=${previousStart}&previous_end=${previousEnd}`;
        }
        
        const response = await fetch(url);
        if (!response.ok) throw new Error('Ошибка при получении данных');
        
        const periodComparison = await response.json();
        window.lastPeriodComparison = periodComparison;
        createPeriodComparisonChart(periodComparison);
    } catch (error) {
        console.error('[Period Comparison] Error:', error);
        alert(`Ошибка: ${error.message}`);
    }
}

window.resetPeriodComparison = function() {
    // Сбрасываем к исходным данным
    if (window.lastPeriodComparison) {
        const currentStart = document.getElementById('currentPeriodStart');
        const currentEnd = document.getElementById('currentPeriodEnd');
        const previousStart = document.getElementById('previousPeriodStart');
        const previousEnd = document.getElementById('previousPeriodEnd');
        
        if (currentStart && currentEnd && window.lastPeriodComparison.current_period) {
            currentStart.value = window.lastPeriodComparison.current_period.start;
            currentEnd.value = window.lastPeriodComparison.current_period.end;
        }
        if (previousStart) previousStart.value = '';
        if (previousEnd) previousEnd.value = '';
        
        createPeriodComparisonChart(window.lastPeriodComparison);
    }
}

// Функция для показа/скрытия полного текста назначения
window.togglePurposeText = function(purposeId) {
    const span = document.getElementById(purposeId);
    if (!span) {
        console.warn('[togglePurposeText] Span not found:', purposeId);
        return;
    }
    
    // Ищем кнопку в родительском div
    const parentDiv = span.parentElement;
    if (!parentDiv) {
        console.warn('[togglePurposeText] Parent div not found');
        return;
    }
    
    const button = parentDiv.querySelector('button');
    if (!button || button.tagName !== 'BUTTON') {
        console.warn('[togglePurposeText] Button not found');
        return;
    }
    
    // Проверяем текущее состояние
    const isExpanded = span.style.whiteSpace === 'normal' || 
                      (span.style.whiteSpace === '' && span.style.maxWidth === 'none');
    
    if (isExpanded) {
        // Сворачиваем
        span.style.whiteSpace = 'nowrap';
        span.style.overflow = 'hidden';
        span.style.textOverflow = 'ellipsis';
        span.style.maxWidth = '280px';
        span.style.wordBreak = 'normal';
        button.textContent = 'Показать полностью';
        console.log('[togglePurposeText] Collapsed text');
    } else {
        // Разворачиваем
        const fullText = span.getAttribute('data-full-text') || span.textContent;
        span.textContent = fullText;
        span.style.whiteSpace = 'normal';
        span.style.overflow = 'visible';
        span.style.textOverflow = 'clip';
        span.style.maxWidth = 'none';
        span.style.wordBreak = 'break-word';
        button.textContent = 'Скрыть';
        console.log('[togglePurposeText] Expanded text');
    }
}

