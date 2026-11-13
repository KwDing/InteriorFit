"""Solve a small dense linear system with pivoting."""


def solve(matrix, rhs):
    rows = [list(row)+[v] for row, v in zip(matrix, rhs)]
    for i in range(len(rows)):
        pivot = max(range(i, len(rows)), key=lambda j: abs(rows[j][i]))
        if abs(rows[pivot][i]) < 1e-9:
            return None
        rows[i], rows[pivot] = rows[pivot], rows[i]
        rows[i] = [v/rows[i][i] for v in rows[i]]
        for j, row in enumerate(rows):
            if j != i:
                rows[j] = [v-row[i]*w for v, w in zip(row, rows[i])]
    return [row[-1] for row in rows]
