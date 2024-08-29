import numpy as np

class GameStateProcessor:
    def __init__(self):
        self.directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]  # up, down, left, right
        self.move_map = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}

    def process_game_state(self, game_state, game_info):
        # Convert game state string to 2D numpy array
        state_array = np.array([list(row) for row in game_state.split('\n')])
        
        # Extract player position
        player_pos = np.where(state_array == 'P')
        player_pos = (player_pos[0][0], player_pos[1][0])

        # Find nearest stone
        stone_positions = np.where(state_array == 'S')
        if len(stone_positions[0]) > 0:
            distances = [self._manhattan_distance(player_pos, (y, x)) for y, x in zip(stone_positions[0], stone_positions[1])]
            nearest_stone = (stone_positions[0][np.argmin(distances)], stone_positions[1][np.argmin(distances)])
        else:
            nearest_stone = None

        # Compute safe moves
        safe_moves = self._get_safe_moves(state_array, player_pos)

        # Decide on the next 10 moves
        moves = self._plan_moves(state_array, player_pos, nearest_stone, safe_moves)

        return moves

    def _manhattan_distance(self, pos1, pos2):
        return abs(pos1[0] - pos2[0]) + abs(pos1[1] - pos2[1])

    def _get_safe_moves(self, state_array, player_pos):
        safe_moves = []
        for dx, dy in self.directions:
            new_pos = (player_pos[0] + dy, player_pos[1] + dx)
            if (0 <= new_pos[0] < state_array.shape[0] and
                0 <= new_pos[1] < state_array.shape[1] and
                state_array[new_pos] in [' ', 'S']):
                safe_moves.append(self.move_map[(dx, dy)])
        return safe_moves

    def _plan_moves(self, state_array, player_pos, nearest_stone, safe_moves):
        moves = []
        current_pos = player_pos

        for _ in range(10):
            if nearest_stone:
                # Check if we're next to a breakable stone
                if self._manhattan_distance(current_pos, nearest_stone) == 1:
                    # Place a bomb
                    moves.append("bomb")
                    # Move away from the bomb
                    for safe_move in safe_moves:
                        dx, dy = self._get_direction_from_move(safe_move)
                        new_pos = (current_pos[0] + dy, current_pos[1] + dx)
                        if state_array[new_pos] == ' ':
                            moves.append(safe_move)
                            current_pos = new_pos
                            break
                    else:
                        moves.append("pass")  # If no safe move, pass
                    nearest_stone = None  # Reset nearest stone after bombing
                else:
                    # Move towards the nearest stone
                    dy = np.sign(nearest_stone[0] - current_pos[0])
                    dx = np.sign(nearest_stone[1] - current_pos[1])
                    move = self.move_map.get((dx, dy))
                    
                    if move in safe_moves:
                        moves.append(move)
                        current_pos = (current_pos[0] + dy, current_pos[1] + dx)
                    else:
                        # If can't move directly towards stone, choose a random safe move
                        random_move = np.random.choice(safe_moves) if safe_moves else "pass"
                        moves.append(random_move)
                        if random_move != "pass":
                            dx, dy = self._get_direction_from_move(random_move)
                            current_pos = (current_pos[0] + dy, current_pos[1] + dx)
            else:
                # If no stones left, move towards the bottom-right corner
                dy = 1 if current_pos[0] < state_array.shape[0] - 2 else 0
                dx = 1 if current_pos[1] < state_array.shape[1] - 2 else 0
                move = self.move_map.get((dx, dy))
                
                if move in safe_moves:
                    moves.append(move)
                    current_pos = (current_pos[0] + dy, current_pos[1] + dx)
                else:
                    moves.append(np.random.choice(safe_moves) if safe_moves else "pass")

            # Find new nearest stone if needed
            if nearest_stone is None:
                stone_positions = np.where(state_array == 'S')
                if len(stone_positions[0]) > 0:
                    distances = [self._manhattan_distance(current_pos, (y, x)) for y, x in zip(stone_positions[0], stone_positions[1])]
                    nearest_stone = (stone_positions[0][np.argmin(distances)], stone_positions[1][np.argmin(distances)])

        return moves

    def _get_direction_from_move(self, move):
        return next((k for k, v in self.move_map.items() if v == move), (0, 0))