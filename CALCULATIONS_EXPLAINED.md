# Объяснение вычислений в TransactionAnalyzer

## 1. Сравнение периодов (Bar Chart)

### Как работает:
1. **Определение текущего периода**: Берем минимальную и максимальную дату из загруженного файла
2. **Вычисление длительности**: `period_days = (current_end - current_start).days + 1`
3. **Поиск предыдущего периода**: 
   - `previous_end = current_start - 1 день`
   - `previous_start = previous_end - period_days`
4. **Агрегация данных**:
   - Доходы: сумма всех транзакций с категорией "Поступление от клиента"
   - Расходы: сумма всех транзакций с другими категориями
   - Баланс: доходы - расходы
5. **Процентное изменение**:
   - `income_change_pct = ((current_income - previous_income) / previous_income) * 100`
   - Аналогично для расходов и баланса

### Где в коде:
- `transaction_history.py`: метод `get_period_comparison()`
- `transaction_analyzer.py`: вызов в `analyze_transactions()` (строки 576-586)

---

## 2. Waterfall Chart для P&L

### Как работает:
1. **Выручка (Revenue)**: Сумма всех транзакций "Поступление от клиента"
2. **COGS (Себестоимость)**: Сумма транзакций "Закупка товара" с подкатегориями "Сырье" или "Комплектующие"
3. **Валовая прибыль (Gross Profit)**: `Revenue - COGS`
4. **Операционные расходы (Operating Expenses)**: Сумма всех расходов (кроме "Поступление от клиента" и "Не принимаемые расходы")
5. **EBITDA (Operating Profit)**: `Gross Profit - Operating Expenses`

### Визуализация:
- Выручка: положительный столбец (зеленый)
- COGS: отрицательный столбец (красный)
- Валовая прибыль: разница между выручкой и COGS
- Операционные расходы: отрицательный столбец (красный)
- EBITDA: итоговый результат

### Где в коде:
- `transaction_analyzer.py`: метод `_generate_pl_report()` (строки 764-782)
- `static/script.js`: функция `createWaterfallChart()` (строки 1518-1619)

---

## 3. Бенчмаркинг с индустрией

### Как работает:

#### Индустриальные бенчмарки (типичные значения для малого/среднего бизнеса в России):
- **CAC Ratio**: 15% (реклама не должна превышать 15% выручки)
- **Валовая маржа**: 30%
- **Операционная маржа (EBITDA)**: 15%
- **Реклама**: 10% выручки
- **Зарплата**: 30% выручки
- **Аренда**: 5% выручки

#### Вычисление текущих показателей:
1. **CAC Ratio**:
   ```python
   advertising = сумма транзакций "Реклама"
   revenue = сумма транзакций "Поступление от клиента"
   cac_ratio = advertising / revenue if revenue > 0 else 0
   ```

2. **Валовая маржа**:
   ```python
   gross_margin = (gross_profit / revenue) * 100
   ```

3. **Операционная маржа**:
   ```python
   operating_margin = (operating_profit / revenue) * 100
   ```

4. **Соотношения расходов**:
   ```python
   salary_ratio = salary / revenue
   rent_ratio = rent / revenue
   advertising_ratio = advertising / revenue
   ```

#### Сравнение:
- Если текущий показатель хуже бенчмарка → предупреждение (warning)
- Если лучше или равен → хорошо (good)

### Где в коде:
- `transaction_analyzer.py`: метод `_calculate_benchmarking()` (строки 1033-1138)

---

## 4. Налоговое планирование на год

### Как работает:

#### 1. Прогноз на год:
```python
# Используем прогноз на 30 дней из forecasts
forecast_30d_income = forecasts["forecast_30d_income"]
forecast_30d_expenses = forecasts["forecast_30d_expenses"]

# Экстраполируем на год (упрощенно: умножаем на 12)
annual_income_forecast = forecast_30d_income * 12
annual_expenses_forecast = forecast_30d_expenses * 12
```

#### 2. Расчет налогов для разных режимов:

**УСН "доходы" (6%)**:
```python
tax_income_mode = annual_income_forecast * 0.06
```

**УСН "доходы минус расходы" (15%)**:
```python
taxable_base = max(annual_income_forecast - annual_expenses_forecast, 0)
tax_expenses_mode = taxable_base * 0.15
effective_rate = (tax_expenses_mode / annual_income_forecast) * 100
```

#### 3. Поиск оптимального режима:
```python
optimal_scenario = min(tax_scenarios, key=lambda x: x["tax"])
potential_savings = current_scenario["tax"] - optimal_scenario["tax"]
```

#### 4. Квартальное планирование:
```python
# Равномерное распределение по кварталам (упрощенно)
quarterly_forecast = {
    "Q1": {"income": annual_income * 0.25, "expenses": annual_expenses * 0.25},
    "Q2": {"income": annual_income * 0.25, "expenses": annual_expenses * 0.25},
    # ... и т.д.
}
```

### Где в коде:
- `transaction_analyzer.py`: метод `_generate_tax_planning()` (строки 1140-1220)
- Использует данные из `_generate_forecasts()` для прогноза

---

## 5. Прогнозы с сезонностью (используется в налоговом планировании)

### Как работает:

#### 1. Определение периода данных:
```python
dates = pd.to_datetime(df["Дата"], errors="coerce").dropna()
if len(dates) > 1:
    period_days = (dates.max() - dates.min()).days + 1
elif len(dates) == 1:
    period_days = 1  # Если только одна транзакция
```

#### 2. Средние дневные расходы/доходы:
```python
avg_daily_expenses = total_expenses / max(period_days, 1)
avg_daily_income = total_income / max(period_days, 1)
```

#### 3. Сезонные коэффициенты (из истории):
```python
# Получаем сезонные паттерны за последний год
seasonal_patterns = transaction_history.get_seasonal_patterns(category, days_back=365)

# Текущий месяц
current_month = datetime.now().month
current_month_key = str(current_month).zfill(2)

# Среднее по всем месяцам
avg_all_months = sum(seasonal_patterns["monthly_avg"].values()) / len(...)

# Сезонный коэффициент для текущего месяца
seasonal_factor = seasonal_patterns["monthly_avg"][current_month_key] / avg_all_months
seasonal_factor = max(0.5, min(2.0, seasonal_factor))  # Ограничение 0.5-2.0
```

#### 4. Прогноз на 30 дней:
```python
forecast_30d_expenses = avg_daily_expenses * 30 * seasonal_factor_expenses
forecast_30d_income = avg_daily_income * 30 * seasonal_factor_income
```

#### 5. Confidence Intervals (95%):
```python
# Используем стандартное отклонение из истории
std = historical_stats["std"]

# 95% доверительный интервал = ±1.96 * std
ci_lower = forecast - 1.96 * std
ci_upper = forecast + 1.96 * std
```

### Где в коде:
- `transaction_analyzer.py`: метод `_generate_forecasts()` (строки 807-1031)
- `transaction_history.py`: метод `get_seasonal_patterns()` (строки 142-188)

---

## 6. Обнаружение аномалий

### Как работает:

#### 1. Всплеск расходов (Outliers):
```python
# Для каждой категории
mean = category_amounts.mean()
std = category_amounts.std()

# Транзакция считается аномалией, если:
outlier = amount > mean + (2.5 * std)  # Порог: 2.5 сигмы
```

#### 2. Новые контрагенты:
```python
# Получаем известных контрагентов из истории (последние 90 дней)
known_counterparties = transaction_history.get_known_counterparties(days_back=90)

# Текущие контрагенты из файла
current_counterparties = set(df["Контрагент"].unique())

# Новые = текущие - известные
new_counterparties = current_counterparties - known_counterparties

# Если сумма платежей новому контрагенту > порога (10,000 ₽) → аномалия
```

#### 3. Отклонение от тренда:
```python
# Историческая статистика по категории
hist_stats = transaction_history.get_category_statistics(category, days_back=90)

# Текущее среднее
current_mean = category_df["Сумма"].abs().mean()
hist_mean = hist_stats["mean"]

# Отклонение
deviation = abs(current_mean - hist_mean) / hist_mean

# Если отклонение > 30% → аномалия
```

#### 4. Негативная динамика (CAC):
```python
# Улучшенный расчет CAC
avg_customer_value = 10000  # Предполагаемый средний чек
estimated_customers = income / avg_customer_value
cac = advertising / estimated_customers

# Сравнение с историческим CAC
hist_cac = historical_advertising / historical_estimated_customers
cac_increase = (cac - hist_cac) / hist_cac

# Если CAC > порога (30% выручки) или вырос на 20% → аномалия
```

### Где в коде:
- `transaction_analyzer.py`: метод `_detect_anomalies()` (строки 616-739)

---

## Итоговая схема вычислений:

```
1. Загрузка файла → Парсинг CSV/XLSX
2. Категоризация транзакций (LLM батчинг)
3. Расчет налогов (базовый)
4. Сохранение в историю
5. Обнаружение аномалий (outliers, новые контрагенты, тренды)
6. Генерация P&L отчета (Revenue → COGS → Gross Profit → EBITDA)
7. Генерация прогнозов (с сезонностью и confidence intervals)
8. Сравнение периодов (текущий vs предыдущий)
9. Бенчмаркинг (сравнение с индустрией)
10. Налоговое планирование (прогноз на год, сравнение режимов)
```

---

*Все вычисления выполняются на backend в Python, результаты передаются на frontend для визуализации в Chart.js*

