values = [3, 5, 6, 9, 1, 2, 0, -1]

def alpha_beta(depth, index, alpha, beta, is_max, visited):
    if depth == 0:
        visited.append(values[index])
        return values[index]
    if is_max:
        best = float('-inf')
        for i in range(2):
            val = alpha_beta(depth-1, index*2 + i, alpha, beta, False, visited)
            best = max(best, val)
            alpha = max(alpha, best)
            if alpha >= beta:  # prune
                break
        return best
    else:
        best = float('inf')
        for i in range(2):
            val = alpha_beta(depth-1, index*2 + i, alpha, beta, True, visited)
            best = min(best, val)
            beta = min(beta, best)
            if beta <= alpha:  # prune
                break
        return best

if __name__ == "__main__":
    visited_nodes = []
    result = alpha_beta(3, 0, float('-inf'), float('inf'), True, visited_nodes)
    print("Optimal value:", result)
    print("Visited leaf nodes:", visited_nodes)
