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
document.getElementById('transactionForm').addEventListener('submit', async (e) => {
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
        const safeMode = escapeHtml(summary.mode || '');
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
        
        // Сохраняем результат для экспорта
        window.lastTransactionResult = data;
        
    } catch (error) {
        console.error('Error:', error);
        const errorMsg = error.message || 'Неизвестная ошибка';
        showResult('transactionResult', 
            `<p class="error-message">❌ Ошибка: ${escapeHtml(errorMsg)}</p>`, true);
    } finally {
        hideLoader(submitButton);
    }
});

// ===== Document Analyzer =====
document.getElementById('documentForm').addEventListener('submit', async (e) => {
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

// ===== Regulatory Consultant =====
document.getElementById('consultantForm').addEventListener('submit', async (e) => {
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
        const formData = new FormData();
        formData.append('result_data', JSON.stringify(window.lastTransactionResult));
        
        const response = await fetch('/api/export/transactions', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error('Ошибка экспорта');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `transactions_${new Date().toISOString().slice(0,10)}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (error) {
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
            <div><strong>Режим:</strong> ${escapeHtml(input.tax_mode || '')}</div>
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

