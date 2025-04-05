import numpy as np
import random
import os
import pickle
import threading
ttable = {}
ttable_lock = threading.Lock()  # ロックを作成

class ZobristHash:
    def __init__(self,hash_file="zobrist_table.npy", transpo_file="transposition_table.pkl"):
        self.board_size = 8
        self.num_pieces = 3  # 1: 空白, 0: 黒, 2: 白
        self.random_table = np.zeros((self.board_size, self.board_size, self.num_pieces), dtype=np.uint64)
        self.hash_file = hash_file
        self.transpo_file = transpo_file

        if os.path.exists(self.hash_file):
            self.random_table = np.load(self.hash_file)
        else:
            np.random.seed(42)
            self.random_table = np.random.randint(1, 2**64, (self.board_size, self.board_size, self.num_pieces), dtype=np.uint64)
            np.save(self.hash_file, self.random_table)

        # トランスポジションテーブルのロード or 初期化
        if os.path.exists(self.transpo_file):
            with open(self.transpo_file, "rb") as f:
                self.transposition_table = pickle.load(f)
            self.transposition_table_base = self.transposition_table
        else:
            self.transposition_table = {}
            self.transposition_table_base = {}

    def delete_other_data(self):
        self.transposition_table = self.transposition_table_base

    def compute_hash(self, board_w,board_b):
        """ 盤面からZobristハッシュ値を計算 """
        hash_value = np.uint64(0)
        for row in range(self.board_size):
            for col in range(self.board_size):
                #piece = board[x][y] + 1  # 1: 白, 0: 空白, -1: 黒 → 2, 1, 0 に変換
                idx = row*8+col
                idx_bit = 1 << idx
                adjust_w = idx_bit & board_w
                if adjust_w:
                    hash_value ^= self.random_table[row][col][2]
                adjust_b = idx_bit & board_b
                if adjust_b:
                    hash_value ^= self.random_table[row][col][0]
                else:
                    hash_value ^= self.random_table[row][col][1]
                """ if piece in [0, 1, 2]:  # 有効な値
                    hash_value ^= self.random_table[x][y][piece] """
        return hash_value
    
    def update_hash(self, current_hash, row, col, old_piece, new_piece):
        """ 1手変更後のハッシュ値を更新（再計算不要） """
        old_piece += 1 # 1: 白, 0: 空白, -1: 黒 → 2, 1, 0 に変換
        new_piece += 1

        current_hash ^= self.random_table[row][col][old_piece]  # 変更前の石を削除
        current_hash ^= self.random_table[row][col][new_piece]  # 変更後の石を追加
        return current_hash
    def save_score(self, board_hash, score,depth,max_pl):
        with ttable_lock:
            """ ハッシュ値とスコアを保存 """
            #self.transposition_table[board_hash] = score
            if (board_hash,max_pl) in (self.transposition_table,max_pl):#その盤面が既出であれば
                existing_depth, existing_score = self.transposition_table[board_hash]
                if depth > existing_depth:  # 深い探索のスコアを優先
                    #print((depth, score))
                    self.transposition_table[(board_hash,max_pl)] = (depth, score)
            else:
                #print((depth, score))
                self.transposition_table[(board_hash,max_pl)] = (depth, score)
            #print("saved")
            #print(self.transposition_table[board_hash])
            #if board_hash in self.transposition_table:
            #    self.transposition_table[board_hash][depth] = score
            #else:
            #    self.transposition_table[board_hash] = {depth: score}
    def get_saved_score(self, board_hash,depth,max_pl):
        """ ハッシュ値からスコアを取得（なければNone） """
        #hash_value = self.compute_hash(board_hash)
        if (board_hash,max_pl) in self.transposition_table:
                #return max(self.transposition_table[board_hash].items(), key=lambda x: x[0])[1]  # 最も深いスコアを取得
            #return self.transposition_table[board_hash].get(depth, None)
            #print("got")
            #print(self.transposition_table[board_hash])
            existing_depth, score = self.transposition_table[(board_hash,max_pl)]
            #print("--------")
            #print(existing_depth)
            #print(score)
            #print("--------")
            if depth <= existing_depth:
                return score
        return None

        #return self.transposition_table.get(board_hash, None)
    def save_table(self):
        """ トランスポジションテーブルをファイルに保存 """
        with ttable_lock:  # ロックを確保
            with open(self.transpo_file, "wb") as f:
                pickle.dump(self.transposition_table, f)