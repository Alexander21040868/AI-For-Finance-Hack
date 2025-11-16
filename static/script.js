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
        
        showResult('transactionResult', html);
        
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
        `;
        
        showResult('documentResult', html);
        
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
        `;
        
        showResult('consultantResult', html);
        
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

// ===== Health Check on Load =====
window.addEventListener('load', async () => {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        console.log('✅ API Health Check:', data);
    } catch (error) {
        console.error('❌ API Health Check Failed:', error);
    }
});

