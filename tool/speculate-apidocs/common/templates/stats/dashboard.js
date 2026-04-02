const { useState, useEffect, useRef } = React;

// --- 1. Helper Functions ---
const formatNumber = (num) => num != null ? new Intl.NumberFormat().format(num) : 'N/A';

const formatDuration = (ms) => {
    if (ms == null || ms < 0) return 'N/A';
    if (ms < 1000) return `${ms}ms`;
    const seconds = (ms / 1000);
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    const paddedSeconds = String(remainingSeconds).padStart(2, '0');
    return `${minutes}m ${paddedSeconds}s`;
};

const formatCost = (cost) => cost != null ? `$${cost.toFixed(6)}` : 'N/A';

const formatStatus = (statusStr) => {
    if (!statusStr) return 'N/A';
    return statusStr.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// Color scheme for charts
const CHART_COLORS = {
    prompt: '#3b82f6',
    completion: '#10b981',
    reasoning: '#8b5cf6',
    callTypes: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16', '#6366f1']
};



// --- 2. Token Breakdown Bar Component ---
const TokenBar = ({ promptTokens = 0, completionTokens = 0, reasoningTokens = 0 }) => {
    // The total tokens are prompt + the full completion. Reasoning is a subset of completion.
    const total = promptTokens + completionTokens;
    if (total === 0) return null;

    // "Spec" tokens are the actual response, i.e., completion minus reasoning.
    const specTokens = Math.max(0, completionTokens - reasoningTokens);

    const promptPercent = (promptTokens / total) * 100;
    const completionPercent = (completionTokens / total) * 100;
    
    // Calculate the breakdown within the completion bar itself.
    const reasoningPercentOfCompletion = completionTokens > 0 ? (reasoningTokens / completionTokens) * 100 : 0;
    const specPercentOfCompletion = completionTokens > 0 ? (specTokens / completionTokens) * 100 : 0;

    return React.createElement('div', { className: 'token-bar-container' },
        React.createElement('div', { className: 'token-bar' },
            promptPercent > 0 && React.createElement('div', { 
                className: 'token-segment prompt',
                style: { width: `${promptPercent}%` },
                title: `Prompt: ${formatNumber(promptTokens)} tokens`
            }, promptPercent > 10 ? formatNumber(promptTokens) : ''),
            
            // The completion part of the bar is a container for its two sub-components: reasoning and spec
            completionPercent > 0 && React.createElement('div', {
                className: 'completion-sub-bar',
                style: { width: `${completionPercent}%`, display: 'flex', height: '100%' }
            },
                reasoningPercentOfCompletion > 0 && React.createElement('div', { 
                    className: 'token-segment reasoning',
                    style: { width: `${reasoningPercentOfCompletion}%` },
                    title: `Reasoning: ${formatNumber(reasoningTokens)} tokens`
                // Show label if the segment's effective width is > 10% of the total bar
                }, ((reasoningPercentOfCompletion / 100) * completionPercent) > 10 ? formatNumber(reasoningTokens) : ''),
                
                specPercentOfCompletion > 0 && React.createElement('div', { 
                    className: 'token-segment completion', // Use 'completion' style for 'spec' tokens
                    style: { width: `${specPercentOfCompletion}%` },
                    title: `Spec: ${formatNumber(specTokens)} tokens`
                }, ((specPercentOfCompletion / 100) * completionPercent) > 10 ? formatNumber(specTokens) : '')
            )
        ),
        React.createElement('div', { className: 'token-breakdown-text' },
            React.createElement('span', null,
                React.createElement('span', { className: 'dot', style: { background: CHART_COLORS.prompt } }),
                `P: ${formatNumber(promptTokens)}`
            ),
            // Replace the confusing 'Completion' and 'Reasoning' legend with the corrected breakdown
            reasoningTokens > 0 && React.createElement('span', null,
                React.createElement('span', { className: 'dot', style: { background: CHART_COLORS.reasoning } }),
                `R: ${formatNumber(reasoningTokens)}`
            ),
            specTokens > 0 && React.createElement('span', null,
                React.createElement('span', { className: 'dot', style: { background: CHART_COLORS.completion } }),
                `S: ${formatNumber(specTokens)}`
            )
        )
    );
};

const Tag = ({ text, type, tooltip = '' }) => {
    const baseStyle = {
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '12px',
        fontSize: '10px',
        fontWeight: '600',
        lineHeight: '1.4',
        marginLeft: '6px',
        border: '1px solid',
    };

    const typeStyles = {
        di_discovered: {
            backgroundColor: '#e0e7ff',
            color: '#4338ca',
            borderColor: '#c7d2fe',
        },
        name_collision: {
            backgroundColor: '#ffedd5',
            color: '#9a3412',
            borderColor: '#fed7aa',
        },
        default: {
            backgroundColor: '#e5e7eb',
            color: '#4b5563',
            borderColor: '#d1d5db',
        },
    };

    const style = { ...baseStyle, ...(typeStyles[type] || typeStyles.default) };

    return React.createElement('span', { style: style, title: tooltip }, text);
};

// --- 3. Chart Components ---
const DonutChart = ({ data, title, canvasId }) => {
    const canvasRef = useRef(null);
    const chartRef = useRef(null);

    useEffect(() => {
        if (!canvasRef.current || !data) return;

        // Destroy existing chart
        if (chartRef.current) {
            chartRef.current.destroy();
        }

        const ctx = canvasRef.current.getContext('2d');
        chartRef.current = new Chart(ctx, {
            type: 'doughnut',
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: { size: 11 }
                        }
                    },
                    title: {
                        display: true,
                        text: title,
                        font: { size: 14, weight: 'bold' }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return `${label}: ${formatNumber(value)} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy();
            }
        };
    }, [data, title]);

    return React.createElement('div', { className: 'chart-container' },
        React.createElement('canvas', { ref: canvasRef, id: canvasId })
    );
};

// --- 4. Basic Components ---
const CodeBlock = ({ content }) => {
    if (!content) return React.createElement('div', { className: 'code-block', style: { color: '#9ca3af' } }, 'No content available.');
    return React.createElement('pre', { className: 'code-block' }, content);
};

const ToggleableCodeBlock = ({ content, buttonTextShow = 'Show', buttonTextHide = 'Hide', defaultExpanded = false }) => {
    const [isExpanded, setIsExpanded] = useState(defaultExpanded);
    const [copied, setCopied] = useState(false);
    
    if (!content) return null;

    const handleCopy = () => {
        navigator.clipboard.writeText(content).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        });
    };

    return React.createElement('div', { style: { marginTop: '5px' } },
        React.createElement('button', {
            className: 'toggle-button',
            onClick: () => setIsExpanded(!isExpanded)
        }, isExpanded ? buttonTextHide : buttonTextShow),
        isExpanded && React.createElement('button', {
            className: `copy-button ${copied ? 'copied' : ''}`,
            onClick: handleCopy
        }, copied ? 'Copied!' : 'Copy'),
        isExpanded && React.createElement(CodeBlock, { content: content })
    );
};

const ValidationAttemptDisplay = ({ attempt, attemptIndex }) => {
    const statusClass = attempt.is_valid ? 'status status-success' : 'status status-failed_validation';
    const statusText = attempt.is_valid ? '✓ Valid' : '✗ Invalid';
    const attemptClass = `validation-attempt ${!attempt.is_valid ? 'failed' : ''}`;

    return React.createElement('div', { className: attemptClass },
        `Validation Attempt ${attemptIndex}: `,
        React.createElement('span', { className: statusClass }, statusText),
        !attempt.is_valid && attempt.errors && attempt.errors.length > 0 && React.createElement('div', { className: 'error-block', style: { marginTop: '4px' } },
            React.createElement('strong', null, 'Errors:'),
            React.createElement('ul', null,
                attempt.errors.map((err, i) => React.createElement('li', { key: i }, err))
            )
        )
    );
};

// --- 5. LLM Call Component with Token Bar ---
const LLMCall = ({ call, validationAttempts = [] }) => {
    const llmCallAttemptNumber = call.model_params?.retry_attempt ?? 0;
    const apiStatus = call.status === 'success' ? 'api_success' : 'api_failed';
    const apiStatusText = call.status === 'success' ? '✓ API Success' : '✗ API Failed';

    return React.createElement('div', { className: 'llm-call' },
        React.createElement('div', { className: 'llm-call-header' },
            React.createElement('strong', null, `${formatStatus(call.call_type)} (LLM Call Attempt ${llmCallAttemptNumber})`),
            React.createElement('span', { className: `status status-${apiStatus}` }, apiStatusText)
        ),
        React.createElement('div', { className: 'llm-call-details' },
            `Provider: ${call.provider || 'N/A'} | Model: ${call.model || 'N/A'} | `,
            `Duration: ${formatDuration(call.duration_ms)} | Total Tokens: ${formatNumber(call.tokens_used)} | Cost: ${formatCost(call.cost_usd)} | `,
            `Finish: ${call.finish_reason || 'N/A'}`
        ),
        // Add Token Bar
        React.createElement(TokenBar, {
            promptTokens: call.prompt_tokens || 0,
            completionTokens: call.completion_tokens || 0,
            reasoningTokens: call.reasoning_tokens || 0
        }),
        call.status === 'failure' && call.error && React.createElement('div', { className: 'error-block' },
            React.createElement('strong', null, `API Error (${call.error_type || 'Unknown'}):`), ` ${call.error}`
        ),
        React.createElement(ToggleableCodeBlock, { content: call.prompt, buttonTextShow: 'Show Prompt', buttonTextHide: 'Hide Prompt' }),
        call.status === 'success' && call.response && React.createElement(ToggleableCodeBlock, { content: call.response, buttonTextShow: 'Show Response', buttonTextHide: 'Hide Response' }),
        call.status === 'success' && validationAttempts.length > 0 && React.createElement('div', { style: { marginTop: '8px', borderTop: '1px dashed #ddd', paddingTop: '8px' } },
            React.createElement('strong', { style: { fontSize: '12px', color: '#374151', display: 'block', marginBottom: '4px' } }, `Validation Result${validationAttempts.length > 1 ? 's' : ''}:`),
            validationAttempts
                .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
                .map((attempt, idx) =>
                    React.createElement(ValidationAttemptDisplay, {
                        key: attempt.attempt_id + '-' + idx,
                        attempt: attempt,
                        attemptIndex: idx
                    })
                )
        )
    );
};

// --- 6. Entity Component with Token Stats ---
const Entity = ({ entity }) => {
    const [expanded, setExpanded] = useState(false);
    const headerStatusClass = entity.status.startsWith('failed') ? 'failed'
        : entity.status === 'partial_success' ? 'partial_success'
        : entity.status === 'ignored' ? 'ignored'
        : 'success';
    const displayStatus = formatStatus(entity.status);

    const allLLMCalls = (entity.llm_requests || [])
        .sort((a, b) => (a.model_params?.retry_attempt ?? 0) - (b.model_params?.retry_attempt ?? 0));

    const validationAttemptsById = (entity.validation_attempts || []).reduce((acc, attempt) => {
        const id = attempt.attempt_id;
        if (!acc[id]) acc[id] = [];
        acc[id].push(attempt);
        return acc;
    }, {});

    const totalEntityRetries = entity.validation_retry_count || 0;

    // Calculate total tokens for this entity
    const totalTokens = allLLMCalls.reduce((sum, call) => sum + (call.tokens_used || 0), 0);
    const totalPromptTokens = allLLMCalls.reduce((sum, call) => sum + (call.prompt_tokens || 0), 0);
    const totalCompletionTokens = allLLMCalls.reduce((sum, call) => sum + (call.completion_tokens || 0), 0);
    const totalReasoningTokens = allLLMCalls.reduce((sum, call) => sum + (call.reasoning_tokens || 0), 0);
    const totalCost = allLLMCalls.reduce((sum, call) => sum + (call.cost_usd || 0), 0);

    const safeEntityId = `entity-${entity.entity_id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
    const tagsToRender = (entity.tags || []).map(tag => {
        let text = tag.replace(/_/g, ' ');
        let tooltip = '';
        if (tag === 'di_discovered' && entity.metadata?.implemented_interface) {
            tooltip = `Implements: ${entity.metadata.implemented_interface}`;
            text = 'DI Discovered';
        } else if (tag.startsWith('schemas_generated:')) {
            text = `📄 ${tag.split(':')[1]} Schemas`; // e.g., "📄 3 Schemas"
        } else if (tag === 'name_collision') {
            text = 'Name Collision';
        } else if (tag === 'duplicate_upgraded') {
            text = 'Duplicate Upgraded';
        } else if (tag === 'same_name_encountered') {
            return null; // Don't render the generic one if we have specifics
        }
        // Add a generic 'type' for styling for the new schema count tag
        const type = tag.startsWith('schemas_generated:') ? 'default' : tag;
        return { text, type: type, tooltip };
    }).filter(Boolean);

    return React.createElement('div', { className: 'entity-item' },
        React.createElement('div', {
            className: `entity-header ${headerStatusClass}`,
            onClick: () => setExpanded(!expanded),
            id: safeEntityId
        },
            React.createElement('span', { className: 'entity-name' },
                `${entity.entity_type === 'endpoint' ? '🔗' : '📄'} ${entity.entity_id}`,
                totalEntityRetries > 0 && React.createElement('span', { className: 'retry-indicator' }, `🔄 ${totalEntityRetries} ${totalEntityRetries === 1 ? 'Retry' : 'Retries'}`),
                tagsToRender.map(tagInfo => React.createElement(Tag, { key: tagInfo.type, ...tagInfo }))
            ),
            React.createElement('div', { className: 'entity-stats' },
                React.createElement('div', { className: 'entity-stat' },
                    React.createElement('span', { className: 'entity-stat-label' }, 'Tokens'),
                    React.createElement('span', { className: 'entity-stat-value' }, formatNumber(totalTokens))
                ),
                React.createElement('div', { className: 'entity-stat' },
                    React.createElement('span', { className: 'entity-stat-label' }, 'Cost'),
                    React.createElement('span', { className: 'entity-stat-value' }, formatCost(totalCost))
                ),
                React.createElement('div', { className: 'entity-stat' },
                    React.createElement('span', { className: 'entity-stat-label' }, 'Duration'),
                    React.createElement('span', { className: 'entity-stat-value' }, formatDuration(entity.duration_ms))
                )
            ),
            React.createElement('span', { className: `status status-${entity.status}` }, displayStatus),
            React.createElement('span', { className: `collapse-icon ${expanded ? 'expanded' : ''}` }, '▶')
        ),
        React.createElement('div', { className: `collapsible-content ${expanded ? 'expanded' : ''}` },
            expanded && React.createElement('div', { className: 'entity-content' },
                React.createElement('div', { style: { marginBottom: '15px' } },
                    React.createElement('h4', { style: { marginTop: 0 } }, 'Token Breakdown'),
                    React.createElement(TokenBar, {
                        promptTokens: totalPromptTokens,
                        completionTokens: totalCompletionTokens,
                        reasoningTokens: totalReasoningTokens
                    })
                ),
                React.createElement('div', { style: { marginBottom: '10px', color: '#4b5563' } },
                    React.createElement('strong', null, 'Started: '), `${new Date(entity.start_time).toLocaleString()} | `,
                    React.createElement('strong', null, 'Ended: '), `${entity.end_time ? new Date(entity.end_time).toLocaleString() : 'N/A'}`
                ),
                entity.metadata?.implemented_interface && React.createElement('div', { 
                    style: { 
                        fontStyle: 'italic', 
                        fontSize: '12px', 
                        color: '#4338ca', // Matching DI tag color
                        backgroundColor: '#eef2ff', 
                        padding: '8px 12px',
                        borderRadius: '6px',
                        border: '1px solid #c7d2fe',
                        marginBottom: '10px' 
                    } 
                },
                    `Discovered via Dependency Injection. Implements Interface: `,
                    React.createElement('strong', null, entity.metadata.implemented_interface)
                ),
                entity.name_conflict_details && entity.name_conflict_details.length > 0 && React.createElement('div', null,
                    React.createElement('h4', null, 'Name Conflict Details'),
                    React.createElement('table', { className: 'table', style: {fontSize: '12px'} },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', null, 'Schema Name'),
                                React.createElement('th', null, 'Resolution'),
                                React.createElement('th', {style: {textAlign: 'left'}}, 'Details')
                            )
                        ),
                        React.createElement('tbody', null,
                            entity.name_conflict_details.map((detail, idx) => 
                                React.createElement('tr', {key: idx},
                                    React.createElement('td', {style: {textAlign: 'left'}}, detail.schema_name),
                                    React.createElement('td', {style: {textAlign: 'left'}},
                                        React.createElement('span', { className: `status status-${detail.resolution.startsWith('collision') ? 'failed_validation' : 'partial_success'}`},
                                            formatStatus(detail.resolution)
                                        )
                                    ),
                                    React.createElement('td', {style: {textAlign: 'left'}},
                                        detail.resolution === 'collision_renamed'
                                            ? `Renamed to "${detail.final_name}" to avoid conflict with existing schema from FQN: ${detail.conflicting_fqn}`
                                            : `Skipped/Upgraded due to existing schema from FQN: ${detail.conflicting_fqn}`
                                    )
                                )
                            )
                        )
                    )
                ),
                entity.extra_code_requested && React.createElement('div', { style: { fontStyle: 'italic', fontSize: '12px', color: '#6b7280', marginBottom: '10px' } },
                    `Extra code requested ${entity.extra_code_count} time(s) for components: ${entity.extra_code_components.join(', ') || 'None specified'}.`
                ),
                entity.status !== 'success' && entity.status !== 'ignored' && entity.error && React.createElement('div', { className: 'error-block', style: { marginBottom: '15px' } },
                    React.createElement('strong', null, `Entity Error (${formatStatus(entity.error_type) || 'Unknown'}):`), ` ${entity.error}`
                ),
                React.createElement('h4', null, 'LLM Calls & Validation History'),
                allLLMCalls.length > 0
                    ? allLLMCalls.map((call, idx) => {
                        const attemptsForThisCall = validationAttemptsById[call.attempt_id] || [];
                        return React.createElement(LLMCall, {
                            key: call.attempt_id || idx,
                            call: call,
                            validationAttempts: attemptsForThisCall
                        });
                    })
                    : React.createElement('p', { style: { color: '#6b7280' } }, 'No LLM calls recorded for this entity.')
            )
        )
    );
};

// --- 7. Cost Analysis Component ---
const CostAnalysis = ({ stats }) => {
    const llmStats = stats.llm_stats || {};
    const callTypeStats = llmStats.by_call_type || {};
    
    // Calculate theoretical cost without optimizations (if we have reasoning token data)
    const totalReasoningTokens = stats.total_reasoning_tokens || 0;
    const actualCost = llmStats.total_cost_usd || 0;
    
    // Group costs by category
    const costByCategory = {
        serializers: 0,
        endpoints: 0,
        agents: 0,
        other: 0
    };
    
    Object.entries(callTypeStats).forEach(([type, data]) => {
        const cost = data.cost_usd || 0;
        if (type.includes('serializer')) {
            costByCategory.serializers += cost;
        } else if (type.includes('endpoint')) {
            costByCategory.endpoints += cost;
        } else if (type.includes('agent')) {
            costByCategory.agents += cost;
        } else {
            costByCategory.other += cost;
        }
    });

    return React.createElement('div', null,
        React.createElement('div', { className: 'grid-3-col' },
            React.createElement('div', { className: 'cost-metric' },
                React.createElement('h4', null, '💰 Total Cost'),
                React.createElement('div', { className: 'value' }, formatCost(actualCost))
            ),
            React.createElement('div', { className: 'cost-metric' },
                React.createElement('h4', null, '📊 Cost per Token'),
                React.createElement('div', { className: 'value' }, 
                    llmStats.total_tokens > 0 
                        ? formatCost(actualCost / llmStats.total_tokens * 1000) + '/1k'
                        : 'N/A'
                )
            ),
            React.createElement('div', { className: 'cost-metric' },
                React.createElement('h4', null, '⚡ Avg Cost per Call'),
                React.createElement('div', { className: 'value' }, 
                    llmStats.total_calls > 0 
                        ? formatCost(actualCost / llmStats.total_calls)
                        : 'N/A'
                )
            )
        ),
        React.createElement('div', { className: 'grid-2-col' },
            React.createElement('div', null,
                React.createElement('h3', null, 'Cost by Category'),
                React.createElement('table', { className: 'table' },
                    React.createElement('thead', null,
                        React.createElement('tr', null,
                            React.createElement('th', null, 'Category'),
                            React.createElement('th', null, 'Cost (USD)'),
                            React.createElement('th', null, '% of Total')
                        )
                    ),
                    React.createElement('tbody', null,
                        Object.entries(costByCategory).map(([category, cost]) =>
                            React.createElement('tr', { key: category },
                                React.createElement('td', null, formatStatus(category)),
                                React.createElement('td', null, formatCost(cost)),
                                React.createElement('td', null, 
                                    actualCost > 0 
                                        ? `${((cost / actualCost) * 100).toFixed(1)}%`
                                        : '0%'
                                )
                            )
                        )
                    )
                )
            ),
            React.createElement('div', null,
                React.createElement('h3', null, 'Cost by Call Type'),
                React.createElement('table', { className: 'table' },
                    React.createElement('thead', null,
                        React.createElement('tr', null,
                            React.createElement('th', null, 'Call Type'),
                            React.createElement('th', null, 'Calls'),
                            React.createElement('th', null, 'Cost (USD)')
                        )
                    ),
                    React.createElement('tbody', null,
                        Object.entries(callTypeStats)
                            .filter(([_, data]) => data.calls > 0)
                            .sort((a, b) => b[1].cost_usd - a[1].cost_usd)
                            .map(([type, data]) =>
                                React.createElement('tr', { key: type },
                                    React.createElement('td', null, formatStatus(type)),
                                    React.createElement('td', null, formatNumber(data.calls)),
                                    React.createElement('td', null, formatCost(data.cost_usd))
                                )
                            )
                    )
                )
            )
        )
    );
};

// --- 8. Main Dashboard Component ---
const StatsDashboard = () => {
    const [activeTab, setActiveTab] = useState('overview');
    const stats = window.statsData || {};
    const llmStats = stats.llm_stats || {};
    const validationStats = stats.validation_stats || {};
    const serializerStats = stats.serializers || { entities: [], status_counts: {}, total: 0 };
    const endpointStats = stats.endpoints || { entities: [], status_counts: {}, total: 0 };
    const callTypeStats = llmStats.by_call_type || {};

    // Prepare data for charts
    const tokenChartData = {
        labels: ['Prompt', 'Completion', 'Reasoning'].filter((_, i) => 
            [llmStats.prompt_tokens, llmStats.completion_tokens, stats.total_reasoning_tokens][i] > 0
        ),
        datasets: [{
            data: [llmStats.prompt_tokens || 0, llmStats.completion_tokens || 0, stats.total_reasoning_tokens || 0].filter(v => v > 0),
            backgroundColor: [CHART_COLORS.prompt, CHART_COLORS.completion, CHART_COLORS.reasoning],
            borderWidth: 2,
            borderColor: '#ffffff'
        }]
    };

    // Prepare call type chart data
    const callTypeChartData = {
        labels: Object.keys(callTypeStats).filter(k => callTypeStats[k].tokens > 0).map(k => formatStatus(k)),
        datasets: [{
            data: Object.values(callTypeStats).filter(v => v.tokens > 0).map(v => v.tokens),
            backgroundColor: CHART_COLORS.callTypes,
            borderWidth: 2,
            borderColor: '#ffffff'
        }]
    };

    // Calculate entity-level token distribution
    const allEntities = [...(serializerStats.entities || []), ...(endpointStats.entities || [])];
    const serializerTokens = serializerStats.entities?.reduce((sum, e) => 
        sum + (e.llm_requests || []).reduce((s, r) => s + (r.tokens_used || 0), 0), 0) || 0;
    const endpointTokens = endpointStats.entities?.reduce((sum, e) => 
        sum + (e.llm_requests || []).reduce((s, r) => s + (r.tokens_used || 0), 0), 0) || 0;

    const entityTypeChartData = {
        labels: ['Serializers', 'Endpoints'].filter((_, i) => [serializerTokens, endpointTokens][i] > 0),
        datasets: [{
            data: [serializerTokens, endpointTokens].filter(v => v > 0),
            backgroundColor: ['#3b82f6', '#10b981'],
            borderWidth: 2,
            borderColor: '#ffffff'
        }]
    };

    const summaryCards = [
        { title: "Total Duration", value: formatDuration(stats.duration_ms), icon: "⏱️" },
        { title: "Total Cost (USD)", value: formatCost(llmStats.total_cost_usd), icon: "💰" },
        { title: "Total Tokens", value: formatNumber(llmStats.total_tokens), icon: "📝" },
        { title: "Endpoints Success", value: `${endpointStats.status_counts?.success || 0}/${endpointStats.total || 0}`, icon: "🔗" },
        { title: "Serializers Success", value: `${serializerStats.status_counts?.success || 0}/${serializerStats.total || 0}`, icon: "📄" },
        { title: "Validation Retries", value: formatNumber(validationStats.total_validation_retries), icon: "🔄" },
    ];

    const failedEntities = allEntities.filter(e => e.status && e.status.startsWith('failed'));
    const highRetryEntities = allEntities
        .filter(e => (e.validation_retry_count || 0) > 0)
        .sort((a, b) => (b.validation_retry_count || 0) - (a.validation_retry_count || 0));

    return React.createElement('div', { className: 'container' },
        React.createElement('div', { className: 'header' },
            React.createElement('h1', { className: 'title' }, 'OpenAPI Generation Stats'),
            React.createElement('p', { className: 'subtitle' }, `Repository: ${stats.repo_name || 'N/A'} | Run ID: ${stats.run_id || 'N/A'}`)
        ),
        
        // Summary Cards
        React.createElement('div', { className: 'grid' },
            summaryCards.map((card, idx) =>
                React.createElement('div', { key: idx, className: 'stat-card' },
                    React.createElement('div', { className: 'icon' }, card.icon),
                    React.createElement('h3', null, card.title),
                    React.createElement('p', null, card.value)
                )
            )
        ),

        // Global Token Breakdown Bar
        React.createElement('div', { className: 'card' },
            React.createElement('h2', null, '📊 Global Token Breakdown'),
            React.createElement(TokenBar, {
                promptTokens: llmStats.prompt_tokens || 0,
                completionTokens: llmStats.completion_tokens || 0,
                reasoningTokens: stats.total_reasoning_tokens || 0
            })
        ),

        // Tabs for different views
        React.createElement('div', { className: 'card' },
            React.createElement('div', { className: 'tabs' },
                React.createElement('button', { 
                    className: `tab ${activeTab === 'overview' ? 'active' : ''}`,
                    onClick: () => setActiveTab('overview')
                }, 'Overview'),
                React.createElement('button', { 
                    className: `tab ${activeTab === 'visualizations' ? 'active' : ''}`,
                    onClick: () => setActiveTab('visualizations')
                }, 'Visualizations'),
                React.createElement('button', { 
                    className: `tab ${activeTab === 'cost' ? 'active' : ''}`,
                    onClick: () => setActiveTab('cost')
                }, 'Cost Analysis')
            ),

            // Tab Content
            activeTab === 'overview' && React.createElement('div', null,
                // LLM Stats Table with Token Bars
                React.createElement('h2', null, 'LLM Call Statistics'),
                React.createElement('table', { className: 'table' },
                    React.createElement('thead', null,
                        React.createElement('tr', null,
                            React.createElement('th', null, 'Call Type'),
                            React.createElement('th', null, 'Calls'),
                            React.createElement('th', null, 'Total Tokens'),
                            React.createElement('th', null, 'Token Breakdown'),
                            React.createElement('th', null, 'Cost (USD)'),
                            React.createElement('th', null, 'Avg Duration')
                        )
                    ),
                    React.createElement('tbody', null,
                        Object.keys(callTypeStats).map((typeKey) => {
                            const data = callTypeStats[typeKey];
                            // We don't have per-call-type breakdown, so we'll show total only
                            return React.createElement('tr', { key: typeKey },
                                React.createElement('td', null, formatStatus(typeKey)),
                                React.createElement('td', null, formatNumber(data.calls)),
                                React.createElement('td', null, formatNumber(data.tokens)),
                                React.createElement('td', { style: { minWidth: '200px' } }, 
                                    data.tokens > 0 ? `${formatNumber(data.tokens)} tokens` : 'N/A'
                                ),
                                React.createElement('td', null, formatCost(data.cost_usd)),
                                React.createElement('td', null, formatDuration(data.avg_duration_ms))
                            );
                        })
                    )
                )
            ),

            activeTab === 'visualizations' && React.createElement('div', null,
                React.createElement('div', { className: 'grid-3-col' },
                    React.createElement('div', null,
                        React.createElement(DonutChart, {
                            data: tokenChartData,
                            title: 'Total Token Distribution',
                            canvasId: 'tokenChart'
                        })
                    ),
                    React.createElement('div', null,
                        React.createElement(DonutChart, {
                            data: callTypeChartData,
                            title: 'Tokens by Call Type',
                            canvasId: 'callTypeChart'
                        })
                    ),
                    React.createElement('div', null,
                        React.createElement(DonutChart, {
                            data: entityTypeChartData,
                            title: 'Tokens by Entity Type',
                            canvasId: 'entityTypeChart'
                        })
                    )
                )
            ),

            activeTab === 'cost' && React.createElement(CostAnalysis, { stats: stats })
        ),

        // Entities sections
        React.createElement('div', { className: 'card' },
            React.createElement('h2', null, `🔗 Endpoints (${endpointStats.total || 0})`),
            React.createElement('div', { className: 'entity-list' },
                (endpointStats.entities && endpointStats.entities.length > 0)
                    ? endpointStats.entities.map((entity, idx) => 
                        React.createElement(Entity, { key: entity.entity_id || idx, entity: entity }))
                    : React.createElement('p', { style: { color: '#6b7280' } }, 'No endpoints processed.')
            )
        ),
        
        React.createElement('div', { className: 'card' },
            React.createElement('h2', null, `📄 Serializers (${serializerStats.total || 0})`),
            React.createElement('div', { className: 'entity-list' },
                (serializerStats.entities && serializerStats.entities.length > 0)
                    ? serializerStats.entities.map((entity, idx) => 
                        React.createElement(Entity, { key: entity.entity_id || idx, entity: entity }))
                    : React.createElement('p', { style: { color: '#6b7280' } }, 'No serializers processed.')
            )
        ),

        // Failure/Retry Analysis
        React.createElement('div', { className: 'card' },
            React.createElement('h2', null, '⚠️ Failure & Retry Analysis'),
            React.createElement('div', { className: 'grid-2-col' },
                React.createElement('div', null,
                    React.createElement('h3', null, `Failed Entities (${failedEntities.length})`),
                    failedEntities.length > 0 ? React.createElement('table', { className: 'table' },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', null, 'Entity ID'),
                                React.createElement('th', null, 'Type'),
                                React.createElement('th', null, 'Final Status'),
                                React.createElement('th', null, 'Error Type')
                            )
                        ),
                        React.createElement('tbody', null,
                            failedEntities.map((entity, idx) => {
                                const safeId = `entity-${entity.entity_id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
                                return React.createElement('tr', { key: `fail-${idx}` },
                                    React.createElement('td', null, 
                                        React.createElement('a', { href: `#${safeId}` }, entity.entity_id)),
                                    React.createElement('td', null, formatStatus(entity.entity_type)),
                                    React.createElement('td', null, 
                                        React.createElement('span', { className: `status status-${entity.status}` }, 
                                            formatStatus(entity.status))),
                                    React.createElement('td', { title: entity.error }, 
                                        formatStatus(entity.error_type) || 'Unknown')
                                );
                            })
                        )
                    ) : React.createElement('p', { style: { color: '#6b7280' } }, 'No entities failed processing.')
                ),
                React.createElement('div', null,
                    React.createElement('h3', null, `Entities with Validation Retries (${highRetryEntities.length})`),
                    highRetryEntities.length > 0 ? React.createElement('table', { className: 'table' },
                        React.createElement('thead', null,
                            React.createElement('tr', null,
                                React.createElement('th', null, 'Entity ID'),
                                React.createElement('th', null, 'Type'),
                                React.createElement('th', null, 'Total Retries'),
                                React.createElement('th', null, 'Final Status')
                            )
                        ),
                        React.createElement('tbody', null,
                            highRetryEntities.map((entity, idx) => {
                                const safeId = `entity-${entity.entity_id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
                                const totalRetries = entity.validation_retry_count || 0;
                                return React.createElement('tr', { key: `retry-${idx}` },
                                    React.createElement('td', null, 
                                        React.createElement('a', { href: `#${safeId}` }, entity.entity_id)),
                                    React.createElement('td', null, formatStatus(entity.entity_type)),
                                    React.createElement('td', { style: { textAlign: 'center' } }, totalRetries),
                                    React.createElement('td', null, 
                                        React.createElement('span', { className: `status status-${entity.status}` }, 
                                            formatStatus(entity.status)))
                                );
                            })
                        )
                    ) : React.createElement('p', { style: { color: '#6b7280' } }, 'No entities triggered validation retries.')
                )
            )
        )
    );
};

// --- 9. Mount the Application ---
const rootElement = document.getElementById('root');
if (rootElement) {
    const reactRoot = ReactDOM.createRoot(rootElement);
    reactRoot.render(React.createElement(StatsDashboard));
} else {
    console.error("Root element (#root) not found for React mounting.");
}