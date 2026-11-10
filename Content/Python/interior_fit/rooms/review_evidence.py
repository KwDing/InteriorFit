"""Explain observable validation status; no reference geometry is available in the UI."""
LABELS = dict(roof_connectivity='顶板连通',walls='墙面补查',heights='地板/顶板高度',
              internal_links='区域内部隔墙',roof_boundary='轮廓外侧顶板')
STATES = dict(passed='通过',pending='未完成',conflict='发现冲突')


def message(result):
    if not result.get('candidate_checks'):
        return ''
    checks = '；'.join(f'{LABELS.get(k,k)}：{STATES.get(v,v)}' for k,v in result['candidate_checks'].items())
    reason = '预算内保留' if result.get('budget_fallback') else '有限采样生成'
    return ('这是'+reason+'的待复核候选，现场 IoU 未知。'+checks+'。'
            '请检查开口、凹口、隔墙与高差后决定是否采纳。')
