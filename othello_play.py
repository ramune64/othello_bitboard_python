import numpy as np
import random
import time
import pyautogui as pag
import torch
from tqdm.auto import tqdm
import zobrist_hash
import os


class MyError(Exception):
    pass

#文字と数字を変換するよ(convert letters to numbers)
convert_l2n = {"a" : 1, "b" : 2, "c" : 3, "d" : 4, "e" : 5, "f" : 6, "g" : 7, "h" : 8}
#数字と文字を変換するよ(convert numbers to letters)
convert_n2l = ["a", "b", "c", "d", "e", "f", "g", "h"]
#白黒をそれぞれ数字に割り当てるよ(使わないかもね)
convert_color = {"white":1,"black":-1}

# 各方向を表すビットマスク
DIRECTIONS = [
    -8,  # 下
    8,   # 上
    -1,  # 右
    1,   # 左
    -9,  # 右下
    9,   # 左上
    -7,  # 左下
    7    # 右上
]
LEFT_MASK =  0b0111111101111111011111110111111101111111011111110111111101111111  # 左端を0にする
RIGHT_MASK = 0b1111111011111110111111101111111011111110111111101111111011111110  # 右端を0にする
safety_maask = 0xFFFFFFFFFFFFFFFF

def convert_act_str2bit(act):
    put_pos_col = convert_l2n[act[0]]-1#文字を数字に変換してインデックスの表記に合わせる
    put_pos_row = int(act[1]) - 1#数字をインデックス表記に合わせる
    bit_row = 7-put_pos_row
    bit_col = 7-put_pos_col
    return(bit_row,bit_col)
def convert_act_bit2str(act):
    bit_row = act[0]
    bit_col = act[1]
    row = 7 - bit_row
    col = 7 - bit_col
    str_act = convert_n2l[col] + str(row+1)
    return str_act

def shift_board(board, shift_value):
    """与えられた方向にボードをシフトする"""
    if shift_value < 0:
        return board >> abs(shift_value)  # 右シフト
    elif shift_value > 0:
        return board << abs(shift_value)  # 左シフト
#石が置けるマスを判定する関数(rowとcolumnが意味上で反転してるけど動きは正しいので放置)
def get_legal_square(player_color:str,current_board_w,current_board_b) -> list:
    """
    石が置けるマスを判定する関数

    Args:
        player_color(str):判定したい石の色"white"or"black"
        current_board(ndarray):判別してほしい盤面を表す配列(8*8の2次元配列)

    Return:
        list:石が置けるマスを入れた1次元配列(無い場合は空の配列)
    """

    legal_list = []

    #プレイヤーの色が黒の時は白と黒を反転させるよ(処理を簡単にする為)
    if player_color == "black":
        current_board_b, current_board_w = current_board_w, current_board_b
    elif player_color == "white":
        pass
    else:
        raise MyError("whiteとblack以外の言葉が入力されています。")
    #print(current_board)
    #白い石(1)があるインデックスを探す
    #white_indexes = np.where(current_board == 1)
    empty = ~(current_board_b | current_board_w)& 0xFFFFFFFFFFFFFFFF
    while current_board_w:
        position = current_board_w & -current_board_w
        index = position.bit_length() - 1
        #row = index // 8
        #col = index % 8
        current_board_w-=position
        only_white = 1 << index
        for direction in DIRECTIONS:
            b_exist = False
            if (only_white&~LEFT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [1,-7,9])) or (only_white&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [-1,7,-9])):
                continue
            shifted_white = shift_board(only_white,direction)
            if (direction in [1,-7,9]) and direction != 8:
                shifted_white_masked = shifted_white & LEFT_MASK
            elif (direction in [-1,7,-9]) and direction != -8:
                shifted_white_masked = shifted_white & RIGHT_MASK
            else:
                shifted_white_masked = shifted_white
            adjust_board = shifted_white_masked & current_board_b

            while adjust_board:
                shifted_white = shift_board(shifted_white,direction)
                b_exist = True
                if (direction in [1,-7,9]) and direction != 8:
                    shifted_white_masked = shifted_white & LEFT_MASK
                elif (direction in [-1,7,-9]) and direction != -8:
                    shifted_white_masked = shifted_white & RIGHT_MASK
                else:
                    shifted_white_masked = shifted_white
                adjust_board = shifted_white_masked & current_board_b
            if b_exist:
                if shifted_white & empty:
                    legal_pos = shifted_white&-shifted_white
                    index = legal_pos.bit_length() - 1
                    if index >= 64:continue
                    row1 = (index // 8)
                    col1 = index % 8
                    #print((row,col))
                    #print((row1,col1))
                    legal_list.append((row1,col1))
    return list(set(legal_list))

#反転する石を判別して反映する関数dayo
def identify_flip_stone(player_color:str,current_board_w,current_board_b,action:str,mode:int=0) -> any:
    """
    反転する石を判別して反映する関数

    Args:
        player_color(str):判定したい石の色"white"or"black"
        current_board(np.ndarray):判別してほしい盤面を表す配列(8*8の2次元配列)
        action(str):石を置く場所(a1~h8)の記述方式
        mode(int=0):0なら変更が反映された盤面の配列が返り値となる
        mode(int=1):1なら裏返す石の場所が入った配列が返り値となる


    Returns:
        ndarray:渡された盤面とアクションを元に石の反転を反映させて盤面を返す(mode=0)
        or
        list:反転する石の場所が入っている(mode=1)
        or
        str:置けない位置に石を置こうとした時は"wrong"と返す(mode=0,1)
    """
    if player_color == "black":
        current_board_b, current_board_w = current_board_w, current_board_b
    elif player_color == "white":
        pass
    else:
        raise MyError("whiteとblack以外の言葉が入力されています。")
    
    if len(action) != 2:
        print(action)
        return "wrong2"
    
    legal_squares = get_legal_square("white",current_board_w,current_board_b)#現状石が置ける場所を確認
    bit_row,bit_col = convert_act_str2bit(action)
    if (bit_row,bit_col) in legal_squares:pass
    else:#石が置けない場所に石を置こうとしていたら
        return "wrong"
    index = bit_row*8 + bit_col
    only_white = 1 << index
    flip_list = []
    for direction in DIRECTIONS:
            black_list = []
            b_exist = False
            if (only_white&~LEFT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [1,-7,9])) or (only_white&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [-1,7,-9])):
                continue
            shifted_white = shift_board(only_white,direction)
            if (direction in [1,-7,9]) and direction != 8:
                shifted_white_masked = shifted_white & LEFT_MASK
            elif (direction in [-1,7,-9]) and direction != -8:
                shifted_white_masked = shifted_white & RIGHT_MASK
            else:
                shifted_white_masked = shifted_white
            adjust_board = shifted_white_masked & current_board_b
            black_list.append(shifted_white)
            while adjust_board:
                shifted_white = shift_board(shifted_white,direction)
                b_exist = True
                if (direction in [1,-7,9]) and direction != 8:
                    shifted_white_masked = shifted_white & LEFT_MASK
                elif (direction in [-1,7,-9]) and direction != -8:
                    shifted_white_masked = shifted_white & RIGHT_MASK
                else:
                    shifted_white_masked = shifted_white
                adjust_board = shifted_white_masked & current_board_b
                black_list.append(shifted_white)#このままだと一番最後の要素は白色の石
            if b_exist:
                if shifted_white&current_board_w:
                    for black in black_list[:-1]:
                        black_pos = black&-black
                        index = black_pos.bit_length() - 1
                        row1 = (index // 8)
                        col1 = index % 8
                        flip_list.append((row1,col1))
    if mode == 0 or mode == 2:#盤面を更新
        flip_bits = 0
        for flip in flip_list:
            index = flip[0]*8 + flip[1]
            flip_bits |= 1<<index
        current_board_b ^= flip_bits
        current_board_w |= flip_bits
        current_board_w |= only_white
        if player_color == "black":
            current_board_b, current_board_w = current_board_w, current_board_b
        if mode == 0:
            return current_board_w,current_board_b
        elif mode == 2:
            return current_board_w,current_board_b,flip_list
    return flip_list

#オセロを配列の上で実際にプレイできるよ
def play_othello(mode1:any,mode2:any,mode3:any,record_data:str="",last_winner:str="") -> str:
    mode1 = str(mode1)
    mode2 = str(mode2)
    mode3 = str(mode3)
    if mode1 == "0":
        mode3 = "0"
    if mode2 == "0":
        print("盤面の一番左上のマスの左上の頂点をクリックせよ")
        left_up_pos = get_board.get_click_pos()#左クリックされた座標を取得(盤面の左上として扱う)
        print("盤面の一番右下のマスの右下の頂点をクリックせよ")
        right_down_pos = get_board.get_click_pos()#左クリックされた座標を取得(盤面の右下として扱う)

        leftup_x,leftup_y = left_up_pos#x,yに分割
        rightdown_x,rightdown_y = right_down_pos#x,yに分割

        w = rightdown_x-leftup_x#差を取って幅とする
        h = rightdown_y-leftup_y#差を取って高さとする
        span_w = int(w/8)
        span_h = int(h/8)
    
    if mode1 == "2":
        if record_data == "":
            wthor_data = input("棋譜データを入力:")
        else:
            wthor_data = record_data
    
    if mode1 == "3" or mode1 == "4":
        # デバイスの指定 (GPUが使えればcuda、なければcpu)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = dataset_loader.OthelloModel_model8()
        #model = dataset_loader.DQN()
        model = model.to(device)  # モデルをGPUに移動
        model.load_state_dict(torch.load("train8_100000.pth")["model_state_dict"])



    #白:1,黒:-1,空白:0
    first_board = np.array([#初期の盤面を表す配列
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 1,-1, 0, 0, 0],
        [0, 0, 0,-1, 1, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0]
    ])
    current_board_white = board_to_bitboard(first_board.copy(),1)&0xFFFFFFFFFFFFFFFF
    current_board_black = board_to_bitboard(first_board.copy(),-1)&0xFFFFFFFFFFFFFFFF
    current_board = [current_board_white,current_board_black]
    #配列を90°回転させる処理(学習データを水増しする為に使う予定)
    #first_board = np.rot90(first_board,2)
    #print(first_board)
    record = ""
    board_record = {"board":[],"action":[]}
    while True:
        #time.sleep(0.01)


        check_black = get_legal_square("black",current_board[0],current_board[1])
        if check_black != []:
            if mode1 == "2":
                next_action = wthor_data[:2]
                #print("残り",len(wthor_data))
                wthor_data = wthor_data.replace(next_action,"",1)
                if last_winner == "b":
                    board_record["board"].append((current_board*-1).tolist())
                    put_col = convert_l2n[next_action[0]]-1#文字を数字に変換してインデックスの表記に合わせる
                    put_row = int(next_action[1]) - 1#数字をインデックス表記に合わせる
                    board_record["action"].append([put_row,put_col])
            can_put = ""
            can_put_list = []
            #print(check_black)
            for square in check_black:
                #can_put += " "+convert_n2l[square[1]]+str(square[0]+1)
                can_put += convert_act_bit2str(square)
                can_put_list.append(convert_act_bit2str(square))
            if mode3 == "0":
                print("置ける場所:"+can_put)

            if mode1 == "0":
                black_action = input("石を置く場所を入力(黒のターン):")
            elif mode1 == "1":
                black_action = random.choice(can_put_list)
                if mode3 == "0":
                    print("石を置く場所を入力(黒のターン):"+black_action)
            elif mode1 == "2":
                black_action = next_action
                if mode3 == "0":
                    print("石を置く場所を入力(黒のターン):"+black_action)
            elif mode1 == "3":#黒がAI
                #current_board_black = current_board.copy()*-1
                predicted_action = predict.predict_action(model,current_board_black)
                string_pos = convert_n2l[predicted_action[1]]+str(predicted_action[0]+1)
                black_action = string_pos
                if mode3 == "0":
                    print("石を置く場所を入力(黒のターン):"+black_action)
            elif mode1 == "4":#黒がランダム
                black_action = random.choice(can_put_list)
                if mode3 == "0":
                    print("石を置く場所を入力(黒のターン):"+black_action)
            elif mode1 == "5":
                #current_board_black = current_board.copy()*-1
                _,black_action,othors = minimax(current_board[1],current_board[0],depth=5,alpha=float('-inf'),beta=float('inf'),maximizing_player=True,other_score=True)
                print(othors)
                print(black_action)
                #print(black_action)
                #black_action = convert_n2l[black_action[1]]+str(black_action[0]+1)
                if mode3 == "0":
                    print("石を置く場所を入力(黒のターン):"+black_action)


            if mode2 == "0":
                put_pos_col = convert_l2n[black_action[0]]-1#文字を数字に変換してインデックスの表記に合わせる
                put_pos_row = int(black_action[1]) - 1#数字をインデックス表記に合わせる
                pag.click(leftup_x+span_w//2+span_w*put_pos_col,leftup_y+span_h//2+span_h*put_pos_row)

            
            record += black_action
            a = identify_flip_stone("black",current_board[0],current_board[1],black_action)
            current_board[0],current_board[1] = a[0],a[1]
            if mode3 == "0":
                print(type(current_board))
                print(current_board.shape)
        else:
            if mode3 == "0":
                print("黒:パス")
        #time.sleep(0.01)
        check_white = get_legal_square("white",current_board[0],current_board[1])
        if check_white != []:
            if mode1 == "2":
                next_action = wthor_data[:2]
                #print("残り",len(wthor_data))
                wthor_data = wthor_data.replace(next_action,"",1)
                if last_winner == "w":
                    board_record["board"].append((current_board).tolist())
                    put_col = convert_l2n[next_action[0]]-1#文字を数字に変換してインデックスの表記に合わせる
                    put_row = int(next_action[1]) - 1#数字をインデックス表記に合わせる
                    board_record["action"].append([put_row,put_col])
            can_put = ""
            can_put_list = []
            for square in check_white:
                can_put += " "+convert_n2l[square[1]]+str(square[0]+1)
                can_put_list.append(convert_n2l[square[1]]+str(square[0]+1))
            if mode3 == "0":
                print("置ける場所:"+can_put)
            if mode1 == "0":
                white_action = input("石を置く場所を入力(白のターン):")
            elif mode1 == "1":
                white_action = random.choice(can_put_list)
                if mode3 == "0":
                    print("石を置く場所を入力(白のターン):"+white_action)
            elif mode1 == "2":
                white_action = next_action
                if mode3 == "0":
                    print("石を置く場所を入力(白のターン):"+white_action)
            elif mode1 == "3" or mode1 == "5":#白がランダム
                white_action = random.choice(can_put_list)
                if mode3 == "0":
                    print("石を置く場所を入力(白のターン):"+white_action)
            elif mode1 == "4":#AI
                current_board_white = current_board.copy()
                predicted_action = predict.predict_action(model,current_board_white)
                string_pos = convert_n2l[predicted_action[1]]+str(predicted_action[0]+1)
                white_action = string_pos
                if mode3 == "0":
                    print("石を置く場所を入力(白のターン):"+white_action)
            if mode1 == "5":
                #current_board_black = current_board.copy()*-1
                _,white_action,othors = minimax(current_board[0],current_board[1],depth=5,alpha=float('-inf'),beta=float('inf'),maximizing_player=True,other_score=True)
                print(othors)
                print(white_action)
            if mode2 == "0":
                put_pos_col = convert_l2n[white_action[0]]-1#文字を数字に変換してインデックスの表記に合わせる
                put_pos_row = int(white_action[1]) - 1#数字をインデックス表記に合わせる
                pag.click(leftup_x+span_w//2+span_w*put_pos_col,leftup_y+span_h//2+span_h*put_pos_row)

            
            record += white_action
            a = identify_flip_stone("white",current_board[0],current_board[1],white_action)
            current_board[0],current_board[1] = a[0],a[1]
            if mode3 == "0":
                print(current_board)
        else:
            if mode3 == "0":
                print("白:パス")
        
        empty = ~(current_board[0] | current_board[1])& 0xFFFFFFFFFFFFFFFF        
        if (check_white == [] and check_black == []) or (empty == 0):
            sum_white = current_board[0].bit_count()
            sum_black = current_board[1].bit_count()
            dis_count = sum_black-sum_white
            dis_count = max(dis_count,dis_count*-1)
            print(record)
            if mode3 == "0":
                print("ーー終了ーー")
                print("黒:",sum_black,"vs","白:",sum_white)
                print(dis_count,"石差で",end="")
            if sum_white > sum_black:
                winner = "w"
                if mode3 == "0":
                    print("白の勝ち")
            elif sum_white < sum_black:
                winner = "b"
                if mode3 == "0":
                    print("黒の勝ち")
            else:
                winner = "d"
                if mode3 == "0":
                    print("引き分け")
            if mode3 == "0":
                print(record)
            break
    if last_winner == "" or last_winner == "d":
        return winner,record
    else:
        return winner,record,board_record

def is_terminal(board_w,board_b):
    #if get_legal_square("white",board) == [] and get_legal_square("black",board.copy()*-1) == []:
    if (board_w | board_b).bit_count() == 64:
        return True
    else:
        return False

def is_within_bounds(x, y, n=8):
    """盤面の範囲内かどうかをチェック"""
    return 0 <= x < n and 0 <= y < n

def get_color_direction_color(board, x, y, dx, dy, last_color):
    n = len(board)
    x += dx
    y += dy
    if is_within_bounds(x, y, n):
        return board[x,y]
    else:
        return "akan"

def get_confirmed_stones(board_w,board_b,mode=0):
    """盤面における確定石の枚数を求める関数"""
    #n = len(board)  # 盤面のサイズ (8x8)
    black_confirmed = 0  # 黒石の確定石を記録する数
    white_confirmed = 0  # 白石の確定石を記録する数
    confirmed_all = 0
    corners = [(0,0),(0,7),(7,0),(7,7)]
    queue = []
    empty = ~(board_b | board_w)& 0xFFFFFFFFFFFFFFFF
    for row,col in corners:
        index = row*8 + col
        corner_bit = 1 << index
        if not corner_bit&empty:
            if corner_bit&board_w:
                confirmed_all |= corner_bit
                white_confirmed |= corner_bit
                queue.append((row,col,1))
            else:
                confirmed_all |= corner_bit
                black_confirmed |= corner_bit
                queue.append((row,col,-1))

    #print("queue",queue)
    # 端の石（隅や辺）の位置をキューに追加
    #directions = [(-1, 0), (0, -1), (0, 1), (1, 0)]
    #directions2 = [(1,1),(1,-1),(-1,1),(-1,-1)]
    #queue = []
    # 確定石を確認する
    #print("queue",queue)
    for s in queue:#垂直方向の探索
        row, col ,origin_color = s
        #print("startpos",(x,y))
        for direction in DIRECTIONS[0:4]:
            #print("dir",(dx,dy))
            last_color = origin_color
            index = row*8 + col
            now_bit = 1 << index
            while True:
                #result = get_color_direction_color(board,nx,ny,dx,dy,last_color)
                if (now_bit&~LEFT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [1,-7,9])) or (now_bit&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [-1,7,-9])):
                    break
                shifted = shift_board(now_bit,direction)
                """ if (direction in [1,-7,9]) and direction != 8:
                    shifted_masked = shifted & LEFT_MASK
                elif direction < 0 and direction != -8:
                    shifted_masked = shifted & RIGHT_MASK
                else:
                    shifted_masked = shifted """
                adjust_board_w = shifted & board_w
                adjust_board_b = shifted & board_b
                #print(last_color,result)
                now_bit = shifted
                if adjust_board_w and last_color == 1:
                    #print("atta!",(nx,ny))
                    confirmed_all |= shifted
                    white_confirmed |= shifted
                    last_color = 1
                elif adjust_board_b and last_color == -1:
                    confirmed_all |= shifted
                    black_confirmed |= shifted
                    last_color = -1
                else:
                    break
    for s in queue:
        row, col ,origin_color = s
        for direction in DIRECTIONS[4:]:
            last_color = origin_color
            index = row*8 + col
            now_bit = 1 << index
            while True:
                if (now_bit&~LEFT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [1,-7,9])) or (now_bit&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF and (direction in [-1,7,-9])):
                    break
                shifted = shift_board(now_bit,direction)
                """ if direction > 0 and direction != 8:
                    shifted_masked = shifted & RIGHT_MASK
                elif direction < 0 and direction != -8:
                    shifted_masked = shifted & LEFT_MASK
                else:
                    shifted_masked = shifted """
                adjust_board_w = shifted & board_w
                adjust_board_b = shifted & board_b
                now_bit = shifted
                if adjust_board_w or adjust_board_b:
                    #print("naname,arimasu")
                    check_list = []#ここに1,2,3,4全てそろえばOK
                    for direction2 in DIRECTIONS:
                        #print("dir",(d2x,d2y))
                        now_bit2 = now_bit
                        last_color2 = last_color
                        #print("startpos",(nx,ny))
                        while True:
                            #print("ココが頭だ")
                            #result2 = get_color_direction_color(board,n2x,n2y,d2x,d2y,last_color2)
                            shifted2 = shift_board(now_bit2,direction2)
                            adjust_board_w2 = shifted2 & board_w
                            adjust_board_b2 = shifted2 & board_b
                            now_bit2 = shifted2
                            #n2x,n2y = n2x + d2x, n2y + d2y
                            #print(last_color2,result2)
                            
                            if adjust_board_w2 or adjust_board_b2:#シフトした先に何かしらの石がある場合
                                if last_color2 == 1:
                                    if white_confirmed&adjust_board_w2:#そのマスが白色の確定石なら
                                        if abs(direction2) == 8:#上下方向の移動なら
                                            check_list.append(2)
                                        elif abs(direction2) == 1:
                                            #print("種類1")
                                            check_list.append(1)
                                        elif direction2 == 7 or direction2 == -7:#右上左下方向の移動なら
                                            #print("種類3")
                                            check_list.append(3)
                                        elif direction2 == -9 or direction2 == 9:#右下左上方向の移動なら
                                            #print(direction2)
                                            #print("種類4_1")
                                            check_list.append(4)
                                        last_color2 = 1
                                        break
                                    else:
                                        last_color2 = -1
                                        break
                                        #print("ここ、確定石。")
                                else:
                                    if black_confirmed&adjust_board_b2:#そのマスが黒色の確定石なら
                                        if abs(direction2) == 8:#上下方向の移動なら
                                            check_list.append(2)
                                        elif abs(direction2) == 1:
                                            #print("種類1")
                                            check_list.append(1)
                                        elif direction2 == 7 or direction2 == -7:#右上左下方向の移動なら
                                            #print("種類3")
                                            check_list.append(3)
                                        elif direction2 == -9 or direction2 == 9:#右下左上方向の移動なら
                                            #print("種類4")
                                            check_list.append(4)
                                        #print("ここ、確定石。")
                                        last_color2 = -1
                                        break
                                    else:
                                        last_color2 = 1
                                        break
                                                                                #右移動                                                 #左移動
                            elif (not shifted2) or shifted2.bit_length() > 64 or ((direction2 in [-1,7,-9]) and shifted2&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction2 in [1,-7,9]) and shifted2&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF):
                                #print("ココ壁っすわ")
                                if abs(direction2) == 8:#上下方向の移動なら
                                    #print(direction2)
                                    check_list.append(2)
                                elif abs(direction2) == 1:
                                    #print("種類1")
                                    #print(direction2)
                                    check_list.append(1)
                                elif direction2 == 7 or direction2 == -7:#右上左下方向の移動なら
                                    #print("種類3")
                                    check_list.append(3)
                                elif direction2 == -9 or direction2 == 9:#右下左上方向の移動なら
                                    check_list.append(4)
                                    #print(direction2)
                                    #print("種類4")
                                break
                            else:
                                break
                    """ for direction2 in DIRECTIONS[4:]:
                        #print("dir",(d2x,d2y))
                        last_color2 = last_color
                        n2x,n2y = nx , ny
                        #print("startpos",(nx,ny))
                        while True:
                            #print("ココが頭だ")
                            #result2 = get_color_direction_color(board,n2x,n2y,d2x,d2y,last_color2)
                            shifted = shift_board(now_bit2,direction2)
                            if direction > 0 and direction != 8:
                                shifted_masked = shifted & LEFT_MASK
                            elif direction < 0 and direction != -8:
                                shifted_masked = shifted & RIGHT_MASK
                            else:
                                shifted_masked = shifted
                            adjust_board_w = shifted_masked & board_w
                            adjust_board_b = shifted_masked & board_b
                            now_bit2 = shifted
                            #n2x,n2y = n2x + d2x, n2y + d2y
                            #print(last_color2,result2)
                            if result2 != last_color2 and result2 != "akan":
                                #print("はいダメー")
                                break

                            if result2 == last_color2:
                                if confirmed_all[n2x,n2y] == 1 or confirmed_all[n2x,n2y] == -1:#1マスずれた先が既に確定石と判明している
                                    #print("ここ、確定石。")
                                    pass
                                else:
                                    #print("ここ、偽物。")
                                    break
                            elif result2 == "akan":
                                #print("ココ壁っすわ")
                                if d2x*d2y == 1:#右上左下方向の移動なら
                                    #print("種類3")
                                    check_list.append(3)
                                if d2x*d2y == -1:#右下左上方向の移動なら
                                    #print("種類4")
                                    check_list.append(4)
                                break
                            last_color2 = result2 """
                    #print(check_list)
                    if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                        #print("新たな確定石、素晴らしい。")
                        if adjust_board_w:
                        #print("atta!",(nx,ny))
                            confirmed_all |= adjust_board_w
                            white_confirmed |= adjust_board_w
                            last_color = 1
                        else:
                            confirmed_all |= adjust_board_b
                            black_confirmed |= adjust_board_b
                            last_color = -1
                else:
                    break
    #return white_confirmed,black_confirmed

    #ここからは他の場所の確定石を数えていきます
    #all_white = np.where(board == 1)
    all_white = []
    get_all_white = board_w
    while get_all_white:
            position = get_all_white & -get_all_white
            get_all_white-=position
            index = position.bit_length() - 1
            #row = index // 8
            #col = index % 8
            only_white = 1 << index
            all_white.append(only_white)
            #(列(上から),行(左から))のタプルの配列に変換
            #all_white = list(zip(all_white[0], all_white[1]))
    #print(all_white)
    for only_white in all_white:
            if not only_white & white_confirmed:#この石がまだ確定石判定を受けていなかったら
                #print("マダ")
                #index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_white
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_white
                    shifted = shift_board(now_bit,direction)
                    """ if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted """
                    adjust_board_w = shifted & board_w
                    adjust_board_b = shifted & board_b
                    """ if abs(direction) == 9:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if black_confirmed & adjust_board_b:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or (shifted.bit_length() > 64) or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (white_confirmed & adjust_board_w) != 0 :#その方向が壁か同じ色の確定石なら
                        """ print("壁or同じ色の確定石")
                        print("同じ色の確定石：",white_confirmed & adjust_board_w)
                        print(direction)
                        if direction == 1:
                            print(bitboard_to_numpy(shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF,0))
                            print(shifted.bit_length()) """
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print("white")
                #print(check_list)
                #リストを変換するよ
                #print(check_list)
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_white
                    white_confirmed |= only_white

    get_all_black = board_b
    all_black = []
    while get_all_black:
            position = get_all_black & -get_all_black
            index = position.bit_length() - 1
            get_all_black-=position
            row = index // 8
            col = index % 8
            #print(row,col)
            only_black = 1 << index
            #(列(上から),行(左から))のタプルの配列に変換
            #all_white = list(zip(all_white[0], all_white[1]))
            all_black.append(only_black)
            

    #print(all_black)
    for only_black in all_black:
            if not only_black & black_confirmed:#この石がまだ確定石判定を受けていなかったら
                index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_black
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_black
                    shifted = shift_board(now_bit,direction)
                    if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted
                    adjust_board_w = shifted_masked & board_w
                    adjust_board_b = shifted_masked & board_b
                    """ if abs(direction) == 7:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if white_confirmed & adjust_board_w:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (black_confirmed & adjust_board_b) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_black
                    black_confirmed |= only_black
    #return white_confirmed,black_confirmed
    #2週目(逆順)
    for only_white in reversed(all_white):
            if not only_white & white_confirmed:#この石がまだ確定石判定を受けていなかったら
                #index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_white
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_white
                    shifted = shift_board(now_bit,direction)
                    """ if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted """
                    adjust_board_w = shifted & board_w
                    adjust_board_b = shifted & board_b
                    """ if abs(direction) == 9:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if black_confirmed & adjust_board_b:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (white_confirmed & adjust_board_w) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction ==-7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print("white")
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_white
                    white_confirmed |= only_white
    for only_black in reversed(all_black):
            if not only_black & black_confirmed:#この石がまだ確定石判定を受けていなかったら
                index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_black
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_black
                    shifted = shift_board(now_bit,direction)
                    if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted
                    adjust_board_w = shifted_masked & board_w
                    adjust_board_b = shifted_masked & board_b
                    """ if abs(direction) == 7:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if white_confirmed & adjust_board_w:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == 9 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == -7:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (black_confirmed & adjust_board_b) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction == 9 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == -7:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_black
                    black_confirmed |= only_black
    
    #3週目
    for only_white in all_white:
            if not only_white & white_confirmed:#この石がまだ確定石判定を受けていなかったら
                #index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_white
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_white
                    shifted = shift_board(now_bit,direction)
                    """ if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted """
                    adjust_board_w = shifted & board_w
                    adjust_board_b = shifted & board_b
                    """ if abs(direction) == 9:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if black_confirmed & adjust_board_b:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (white_confirmed & adjust_board_w) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction ==-7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print("white")
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_white
                    white_confirmed |= only_white
    for only_black in all_black:
            if not only_black & black_confirmed:#この石がまだ確定石判定を受けていなかったら
                index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_black
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_black
                    shifted = shift_board(now_bit,direction)
                    if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted
                    adjust_board_w = shifted_masked & board_w
                    adjust_board_b = shifted_masked & board_b
                    """ if abs(direction) == 7:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if white_confirmed & adjust_board_w:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == 9 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == -7:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (black_confirmed & adjust_board_b) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction == 9 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == -7:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_black
                    black_confirmed |= only_black
    #4週目(逆順)
    for only_white in all_white:
            if not only_white & white_confirmed:#この石がまだ確定石判定を受けていなかったら
                #index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_white
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_white
                    shifted = shift_board(now_bit,direction)
                    """ if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted """
                    adjust_board_w = shifted & board_w
                    adjust_board_b = shifted & board_b
                    """ if abs(direction) == 9:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if black_confirmed & adjust_board_b:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == -7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (white_confirmed & adjust_board_w) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction ==-7 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == 9:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print("white")
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_white
                    white_confirmed |= only_white
    for only_black in reversed(all_black):
            if not only_black & black_confirmed:#この石がまだ確定石判定を受けていなかったら
                index = only_black.bit_length() - 1
                #row = index // 8
                #col = index % 8
                #print(row,col)
                check_list = []
                now_bit = only_black
                for direction in DIRECTIONS:
                    #nx,ny = wx,wy
                    #result = get_color_direction_color(board,nx,ny,dx,dy,0)
                    now_bit = only_black
                    shifted = shift_board(now_bit,direction)
                    if direction > 0 and direction != 8:
                        shifted_masked = shifted & LEFT_MASK
                    elif direction < 0 and direction != -8:
                        shifted_masked = shifted & RIGHT_MASK
                    else:
                        shifted_masked = shifted
                    adjust_board_w = shifted_masked & board_w
                    adjust_board_b = shifted_masked & board_b
                    """ if abs(direction) == 7:
                        print(direction)
                        print(bitboard_to_numpy(0,now_bit))
                        print(bitboard_to_numpy(0,shifted))
                        print(shifted&~LEFT_MASK) """
                    if white_confirmed & adjust_board_w:#その方向が違う色の確定石なら
                        #print("w")
                        #print(direction)
                        if abs(direction) == 8:#上下方向の移動なら
                            #print(6)
                            check_list.append(6)
                        elif abs(direction) == 1:
                            check_list.append(5)
                        elif direction == 9 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(7)
                        elif direction == -9 or direction == -7:#右下左上方向の移動なら
                            check_list.append(8)
                    elif (not shifted) or shifted.bit_length() > 64 or ((direction in [-1,7,-9]) and shifted&~LEFT_MASK&0xFFFFFFFFFFFFFFFF) or ((direction in [1,-7,9]) and shifted&~RIGHT_MASK&0xFFFFFFFFFFFFFFFF) or (black_confirmed & adjust_board_b) :#その方向が壁か同じ色の確定石なら
                        #print(black_confirmed & adjust_board_b)
                        #print("b")
                        #print(direction)
                        
                        if abs(direction) == 8:#上下方向の移動なら
                            check_list.append(2)
                        elif abs(direction) == 1:
                            check_list.append(1)
                        elif direction == 9 or direction == 7:#右上左下方向の移動なら
                            #print("種類3")
                            check_list.append(3)
                        elif direction == -9 or direction == -7:#右下左上方向の移動なら
                            check_list.append(4)
                    #else:
                        #print("u")
                        #print(direction)
                #print(check_list)
                #リストを変換するよ
                for num in [5,6,7,8]:
                    if check_list.count(num) == 2:
                        check_list = [x for x in check_list if x != num]#その値を全て削除
                        check_list.append(num-4)
                
                if (1 in check_list) and (2 in check_list) and (3 in check_list) and (4 in check_list):
                    confirmed_all |= only_black
                    black_confirmed |= only_black    

    # 確定石の数を数える
    #black_confirmed_count = np.sum(black_confirmed)
    #white_confirmed_count = np.sum(white_confirmed)

    #return black_confirmed_count, white_confirmed_count
    return white_confirmed,black_confirmed


scores = np.array([
    [ 30, -12,   0,  -1,  -1,   0, -12,  30],
    [-12, -15,  -3,  -3,  -3,  -3, -15, -12],
    [  0,  -3,   0,  -1,  -1,   0,  -3,   0],
    [ -1,  -3,  -1,  -1,  -1,  -1,  -3,  -1],
    [ -1,  -3,  -1,  -1,  -1,  -1,  -3,  -1],
    [  0,  -3,   0,  -1,  -1,   0,  -3,   0],
    [-12, -15,  -3,  -3,  -3,  -3, -15, -12],
    [ 30, -12,   0,  -1,  -1,   0, -12,  30]
])#計-124
score_flat = scores.flatten()

cx_zone = [(0,1),(1,1),(1,0),(0,6),(1,7),(1,6),(6,0),(6,1),(7,1),(6,7),(7,6),(6,6)]
c_zone = [(0,1),(0,6),(1,7),(6,7),(7,1),(7,6),(1,0),(6,0)]
cx_zone0 = [(0,1),(1,1),(1,0)]
cx_zone1 = [(0,6),(1,7),(1,6)]
cx_zone2 = [(6,0),(6,1),(7,1)]
cx_zone3 = [(6,7),(7,6),(6,6)]

corner = [(0,0),(0,7),(7,7),(7,0)]
m1_e = 0x7E
m1_c = 0x81
m3_e = 0x7E00000000000000
m3_c = 0x8100000000000000
m4_e = 0x0001010101010100
m4_c = 0x0100000000000001
m2_e = 0x0080808080808000
m2_c = 0x8000000000000080
m_e_list = [m1_e,m2_e,m3_e,m4_e]
m_c_list = [m1_c,m2_c,m3_c,m4_c]

def evaluate_board(board_w,board_b):
    con_weight = 4
    empty = ~(board_w | board_b)& 0xFFFFFFFFFFFFFFFF
    turn = 64 - empty.bit_count()
    #print("turn:",turn)
    alpha = max(0, (turn - 40) / 20)  # 40手目以降、徐々に石の数を重視
    num_w = get_legal_square("white",board_w,board_b)
    num_b = get_legal_square("black",board_w,board_b)
    """ if board[0,0] != 1:
        w_cx0 = sum(x in cx_zone0 for x in num_w)
    elif board[0,0] != -1:
        b_cx0 = sum(x in cx_zone0 for x in num_b)
    if board[0,7] != 1:
        w_cx1 = sum(x in cx_zone1 for x in num_w)
    elif board[0,7] != -1:
        b_cx1 = sum(x in cx_zone1 for x in num_b)
    if board[7,0] != 1:
        w_cx2 = sum(x in cx_zone2 for x in num_w)
    elif board[7,0] != -1:
        b_cx2 = sum(x in cx_zone2 for x in num_b)
    if board[7,7] != 1:
        w_cx3 = sum(x in cx_zone3 for x in num_w)
    elif board[7,7] != -1:
        b_cx3 = sum(x in cx_zone3 for x in num_b) """
    
    w_cx = sum(x in cx_zone for x in num_w)
    
    #w_corner = sum(x in corner for x in num_w)
    b_cx = sum(x in cx_zone for x in num_b)
    zennmetu_keikoku = 0
    if board_w.bit_count() <= 2 and turn>=10:
        zennmetu_keikoku = -45

    #1辺全部1色かつ角が相手にとられないなら加点
    edge_point_w = 0
    edge_point_b = 0
    #print(board)
    for idx in range(0,7,2):
        dec_point = 0
        add_point = 0
        """ s = c_zone[idx]
        g = c_zone[idx+1]
        if s[0] == g[0]:
            increase_idx = 1
            increase_s = s[1]
            fix_num = s[0]#固定するインデックスの値
        else:
            increase_idx = 0
            increase_s = s[0]
            fix_num = s[1] """
        #白について実行
        w_num = 0
        w_num = (board_w&m_e_list[idx//2]).bit_count()

        b_num = (board_b&m_e_list[idx//2]).bit_count()
        """ for edge in range(6):
            #print("edge",edge)
            if increase_idx == 1:
                pos = (fix_num,increase_s+edge)
            else:
                pos = (increase_s+edge,fix_num)
            #print("pos:",pos)
            #print("color:",board[pos])
            index = pos[0]*8 + pos[1]
            only_bit = 1 << index
            if board_w&only_bit:#該当箇所が白
                w_num += 1
            else:
                break """
        #print(w_num)
        if w_num == 6:
            c = [0,0]
            m_corner = m_c_list[idx//2]
            for i in range(2):
                position = m_corner & -m_corner
                m_corner -= position
                c_index = position.bit_length() - 1
                #既に角にどちらかの石がある場合
                """ c_pos = corner[idx//2-4]
                c_index = c_pos[0]*8 + c_pos[1] """
                c_bit = 1 << c_index
                adjust_board_w = c_bit & board_w
                if not empty&c_bit:
                    if adjust_board_w:
                        c[i] = 1
                    else:
                        c[i] = -1
            #if c1 == c2:
            #    pass#減点なし
            #elif c1 != c2 and c1 != 0 and c2 != 0:
            #    pass#減点なし
            c1,c2 = c
            if c1 != c2 and ((c1 == 0 and c2 == -1) or (c1 == -1 and c2 == 0)):#角に敵の石が既にあるとき
                #減点の対象
                #print("角に敵の石が既にあるとき")
                dec_point += 10*6*con_weight* 4/5/10
            #敵の合法手が角にある場合
            if corner[idx//2-4] in num_b or corner[idx//2+1-4] in num_b:
                #print("敵の合法手が角にある場合")
                #減点の対象
                dec_point += 10*6*con_weight* 3/5/10
            else:#ない場合
                #加点の対象
                #print("加点や！")
                add_point += 10*6*con_weight* 4/5/10
            edge_point_w += add_point
            edge_point_w -= dec_point
            dec_point = 0
            add_point = 0

        if b_num == 6:
            c = [0,0]
            m_corner = m_c_list[idx//2]
            for i in range(2):
                position = m_corner & -m_corner
                m_corner -= position
                c_index = position.bit_length() - 1
                #既に角にどちらかの石がある場合
                """ c_pos = corner[idx//2-4]
                c_index = c_pos[0]*8 + c_pos[1] """
                c_bit = 1 << c_index
                adjust_board_w = c_bit & board_w
                if not empty&c_bit:
                    if adjust_board_w:
                        c[i] = 1
                    else:
                        c[i] = -1
                #if c1 == c2:
                #    pass#減点なし
                #elif c1 != c2 and c1 != 0 and c2 != 0:
                #    pass#減点なし
                c1,c2 = c
                if c1 != c2 and ((c1 == 0 and c2 == 1) or (c1 == 1 and c2 == 0)):#角に敵の石が既にあるとき
                    #減点の対象
                    dec_point += 10*6*con_weight* 4/5/10
                #敵の合法手が角にある場合
                if corner[idx//2-4] in num_w or corner[idx//2+1-4] in num_w:
                    #減点の対象
                    dec_point += 10*6*con_weight* 3/5/10
                else:#ない場合
                    #加点の対象
                    add_point += 10*6*con_weight* 4/5/10
        edge_point_b += add_point - dec_point

    edge_point = edge_point_w - edge_point_b


    #b_corner = sum(x in corner for x in num_b)
    dis_num = (len(num_w)-w_cx) - (len(num_b)-b_cx)
    #score = (1-alpha) * dis_num + (1 - alpha) * np.sum(scores * board) *2.4 + alpha * np.sum(board) *1.5 *2.4
    # 黒の評価値（black_boardの位置にある評価値を合計）
    black_score = np.sum(score_flat * ((board_b >> np.arange(64,dtype=object)) & 1))

    # 白の評価値（white_boardの位置にある評価値を合計）
    white_score = np.sum(score_flat * ((board_w >> np.arange(64,dtype=object)) & 1))
    #print(white_score)
    #print(black_score)
    board_score = white_score - black_score
    b_snum = board_b.bit_count()
    w_snum = board_w.bit_count()
    #(合法手の差 + 盤面スコア)*1.1*(1-alpha)+alptha*(枚数差)*1.5
    score = (1-alpha) * (dis_num +  board_score*110/100) + alpha * (w_snum-b_snum)*150/100
        #score = np.sum(board * scores)
        #print(score,np.sum(board)*1.5)
    """ else:
        board = w_board.copy() * -1
        score = sum(sum(board * scores_fin)) """
    #print("score",board)

    w_c,b_c = get_confirmed_stones(board_w,board_b)
    w_c,b_c = w_c.bit_count(),b_c.bit_count()
    con_score = (w_c - b_c)
    """ print(board_score)
    print("con:",con_score)
    print("edge",edge_point)
    print("nomal:",score)
    print("dis:",dis_num)
    #print(alpha)
    print(zennmetu_keikoku)
    #print(score)
    #print(con_score*con_weight)
    print(edge_point) """
    
    return  (score*10 + con_score*con_weight*10 + edge_point*10)/10 + zennmetu_keikoku

mask1 = 0xF0F0F0F00F0F0F0F#4*4の右下と左上のマスク
not_mask1 = ~mask1&safety_maask#動かないところ
mask2_l = 0xF0F0F0F0F0F0F0F0#左右反転用マスク(左)
mask2_r = 0x0F0F0F0F0F0F0F0F#左右反転用マスク(左)
mask3_1 = 0x0000333300003333#2*2の右下のマスク
mask3_2 = 0xCCCC0000CCCC0000#2*2の左下のマスク
not_mask3 = ~(mask3_1|mask3_2)&safety_maask
mask4_r = 0x3333333333333333#左右反転用マスク(左)
mask4_l = 0xCCCCCCCCCCCCCCCC#左右反転用マスク(左)
mask5_1 = 0x0055005500550055#1*1の右下のマスク
mask5_2 = 0xAA00AA00AA00AA00#1*1の左下のマスク
mask6_r = 0x5555555555555555#左右反転用マスク(左)
mask6_l = 0xAAAAAAAAAAAAAAAA#左右反転用マスク(左)
not_mask5 = ~(mask5_1|mask5_2)&safety_maask
def rotate90(board):
    t4 = ((board&mask1)<<36|(board&mask1)>>36)|(board&not_mask1)#4*4
    t4m = (t4&mask2_r)<<4|(t4&mask2_l)>>4#4*4左右ミラー
    t2 = (t4m&mask3_1)<<18|(t4m&mask3_2)>>18|(t4m&not_mask3)#2*2
    t2m = (t2&mask4_r)<<2|(t2&mask4_l)>>2#2*2左右ミラー
    t1 = (t2m&mask5_1)<<9|(t2m&mask5_2)>>9|(t2m&not_mask5)#1*1
    t1m = (t1&mask6_r)<<1|(t1&mask6_l)>>1#1*1左右ミラー
    return t1m


# すでに探索した盤面を保存する（トランスポジションテーブル）
zobristhash = zobrist_hash.ZobristHash()
def minimax(board_w,board_b,depth,alpha, beta,maximizing_player,boardhash=None,other_score=False):
    #board1 = board.copy()
    if boardhash == None:
        boardhash = zobristhash.compute_hash(board_w,board_b)
    #print("-------depth---------",depth)
    #print(is_terminal(board1))
    if depth == 0 or is_terminal(board_w,board_b):    #ここが葉ノードなら
        #print("-----葉ノード-----")
        score = evaluate_board(board_w,board_b)
        #if score == float("inf"):
            #print("inf")
            #print(board1)

        return score, None  # 盤面評価値を返す
    #print("board",board1)
    other_scores = {}
    if maximizing_player:
        #print("aTrue")
        legal_list=get_legal_square("white",board_w,board_b)
        #legal_list = sorted(legal_list,key=lambda x:new_board_and_eval(x,board1.copy(),"white"),reverse=True)
        if legal_list == []:
            return minimax(board_w,board_b,depth-1,alpha,beta,False,boardhash)
        max_eval = float('-inf')
        best_move = None
        for move in legal_list:
            #move_string = convert_n2l[move[1]]+str(move[0]+1)
            move_string = convert_act_bit2str(move)
            #print("depth:",depth)
            #print("move:",move_string)
            #print("move",move_string)
            #print("depth",depth)
            #print("mae",board1)
            new_board_w,new_board_b,flip_list = identify_flip_stone("white",board_w,board_b,move_string,mode=2)
            """ board_combined = bitboard_to_numpy(new_board_w, new_board_b)
            print(board_combined) """
            #print("new",new_board)
            new_boardhash = zobristhash.update_hash(boardhash,move[0],move[1],0,1)#新たに置かれた石の処理
            for flip in flip_list:
                new_boardhash = zobristhash.update_hash(new_boardhash,flip[0],flip[1],-1,1)#ひっくり返る石の処理
            #print(new_boardhash)
            eval = zobristhash.get_saved_score(new_boardhash,depth-1,False)
            if eval != None:
                pass
                #print("既出や1")
            else:
                new_board_90_w,new_board_90_b = rotate90(board_w),rotate90(board_b)
                boardhash_90 = zobristhash.compute_hash(new_board_90_w,new_board_90_b)
                eval = zobristhash.get_saved_score(boardhash_90,depth-1,False)
                if eval is None:
                    new_board_180_w,new_board_180_b = rotate90(new_board_90_w),rotate90(new_board_90_b)
                    boardhash_180 = zobristhash.compute_hash(new_board_180_w,new_board_180_b)
                    eval = zobristhash.get_saved_score(boardhash_180,depth-1,False)
                    if eval is None:
                        new_board_270_w,new_board_270_b = rotate90(new_board_180_w),rotate90(new_board_180_b)
                        boardhash_270 = zobristhash.compute_hash(new_board_270_w,new_board_270_b)
                        eval = zobristhash.get_saved_score(boardhash_270,depth-1,False)
                        if eval is None:
                            #if eval == float('inf') or eval == float('-inf'):
                            #    print(eval)
                            #    print(new_board)
                            #    print(depth-1)
                            eval ,_ = minimax(new_board_w,new_board_b,depth-1,alpha, beta,False,new_boardhash)
                            zobristhash.save_score(new_boardhash,eval,depth-1,False)#評価値と盤面の対応を保存
            #print("score:",eval)
            if other_score:
                other_scores[move_string] = eval

                #transposition_table[boardhash] = eval
            if eval > max_eval:
                max_eval = eval
                best_move = move_string
            alpha = max(alpha, eval)  # αを更新
            if beta <= alpha:  # αβ枝刈り
                break
        if other_score:
            return max_eval,best_move,other_scores
        return max_eval,best_move
    else:
        #print("aFalse")
        legal_list=get_legal_square("black",board_w,board_b)
        #legal_list = sorted(legal_list,key=lambda x:new_board_and_eval(x,board1.copy(),"black"),reverse=False)
        min_eval = float('inf')
        best_move = None
        #evals = []
        evals_c = []
        if legal_list == []:
            return minimax(board_w,board_b,depth-1,alpha,beta,True,boardhash)

        for move in legal_list:
            move_string = convert_act_bit2str(move)
            #print(move_string)
            #print("move",move_string)
            #print("depth",depth)
            #print("mae",board1)
            new_board_w,new_board_b,flip_list = identify_flip_stone("black",board_w,board_b,move_string,mode=2)
            #print(a)
            
            #print("new",new_board)
            new_boardhash = zobristhash.update_hash(boardhash,move[0],move[1],0,-1)#新たに置かれた石の処理
            for flip in flip_list:
                new_boardhash = zobristhash.update_hash(new_boardhash,flip[0],flip[1],1,-1)#ひっくり返る石の処理
            eval = zobristhash.get_saved_score(new_boardhash,depth-1,True)
            if eval != None:
                pass
                #print("既出や1")
            else:
                new_board_90_w,new_board_90_b = rotate90(board_w),rotate90(board_b)
                boardhash_90 = zobristhash.compute_hash(new_board_90_w,new_board_90_b)
                eval = zobristhash.get_saved_score(boardhash_90,depth-1,True)
                if eval is None:
                    new_board_180_w,new_board_180_b = rotate90(new_board_90_w),rotate90(new_board_90_b)
                    boardhash_180 = zobristhash.compute_hash(new_board_180_w,new_board_180_b)
                    eval = zobristhash.get_saved_score(boardhash_180,depth-1,True)
                    if eval is None:
                        new_board_270_w,new_board_270_b = rotate90(new_board_180_w),rotate90(new_board_180_b)
                        boardhash_270 = zobristhash.compute_hash(new_board_270_w,new_board_270_b)
                        eval = zobristhash.get_saved_score(boardhash_270,depth-1,True)
                        if eval is None:
                            #if eval == float('inf') or eval == float('-inf'):
                            #    print(eval)
                            #    print(new_board)
                            #    print(depth-1)
                            eval ,_ = minimax(new_board_w,new_board_b,depth-1,alpha, beta,True,new_boardhash)
                            zobristhash.save_score(new_boardhash,eval,depth-1,True)#評価値と盤面の対応を保存
            if other_score:
                other_scores[move_string] = eval
                #transposition_table[boardhash] = eval
            #evals.append(eval)
            if eval < min_eval:
                min_eval = eval
                best_move = move_string
            beta = min(beta, eval)  # αを更新
            if beta <= alpha:  # αβ枝刈り
                break
        #if min_eval == float("inf"):
            #print("min")
            #print(min_eval)
            #print(evals)
            #print(evals_c)
            #print(legal_list)
        if other_score:
            return min_eval,best_move,other_scores
        return min_eval,best_move
zobristhash_AI = zobrist_hash.ZobristHash(transpo_file="transposition_table_AI.pkl")
def minimax_useAI(board_w,board_b,depth,alpha, beta,maximizing_player,boardhash=None,other_score=False):
    #board1 = board.copy()
    if depth == 0 or is_terminal(board_w,board_b):    #ここが葉ノードなら
        #print("-----葉ノード-----")
        #score = evaluate_board(board_w,board_b)
        #if score == float("inf"):
            #print("inf")
            #print(board1)

        return None, None  # 盤面評価値を返す
    if boardhash == None:
        boardhash = zobristhash_AI.compute_hash(board_w,board_b)
    #print("-------depth---------",depth)
    #print(is_terminal(board1))
    
    #print("board",board1)
    other_scores = {}
    if maximizing_player:
        #print("aTrue")
        legal_list=get_legal_square("white",board_w,board_b)
        #legal_list = sorted(legal_list,key=lambda x:new_board_and_eval(x,board1.copy(),"white"),reverse=True)
        if legal_list == []:
            return minimax_useAI(board_w,board_b,depth-1,alpha,beta,False,boardhash)
        max_eval = float('-inf')
        best_move = None
        for move in legal_list:
            #move_string = convert_n2l[move[1]]+str(move[0]+1)
            move_string = convert_act_bit2str(move)
            if depth == 1:
                index = move[0]*8 + move[1]
                eval_list = predict.predict_minimax(board_w,board_b)
                eval = eval_list[index]
                return eval,None
            #print("depth:",depth)
            #print("move:",move_string)
            #print("move",move_string)
            #print("depth",depth)
            #print("mae",board1)
            new_board_w,new_board_b,flip_list = identify_flip_stone("white",board_w,board_b,move_string,mode=2)
            """ board_combined = bitboard_to_numpy(new_board_w, new_board_b)
            print(board_combined) """
            #print("new",new_board)
            new_boardhash = zobristhash_AI.update_hash(boardhash,move[0],move[1],0,1)#新たに置かれた石の処理
            for flip in flip_list:
                new_boardhash = zobristhash_AI.update_hash(new_boardhash,flip[0],flip[1],-1,1)#ひっくり返る石の処理
            #print(new_boardhash)
            eval = zobristhash_AI.get_saved_score(new_boardhash,depth-1,False)
            if eval != None:
                pass
                #print("既出や1")
            else:
                new_board_90_w,new_board_90_b = rotate90(board_w),rotate90(board_b)
                boardhash_90 = zobristhash_AI.compute_hash(new_board_90_w,new_board_90_b)
                eval = zobristhash_AI.get_saved_score(boardhash_90,depth-1,False)
                if eval is None:
                    new_board_180_w,new_board_180_b = rotate90(new_board_90_w),rotate90(new_board_90_b)
                    boardhash_180 = zobristhash_AI.compute_hash(new_board_180_w,new_board_180_b)
                    eval = zobristhash_AI.get_saved_score(boardhash_180,depth-1,False)
                    if eval is None:
                        new_board_270_w,new_board_270_b = rotate90(new_board_180_w),rotate90(new_board_180_b)
                        boardhash_270 = zobristhash_AI.compute_hash(new_board_270_w,new_board_270_b)
                        eval = zobristhash_AI.get_saved_score(boardhash_270,depth-1,False)
                        if eval is None:
                            #if eval == float('inf') or eval == float('-inf'):
                            #    print(eval)
                            #    print(new_board)
                            #    print(depth-1)
                            eval ,_ = minimax_useAI(new_board_w,new_board_b,depth-1,alpha, beta,False,new_boardhash)
                            if eval == None:
                                index = move[0]*8 + move[1]
                                eval_list = predict.predict_minimax(board_w,board_b)
                                eval = eval_list[index]
                                return eval,None
                            zobristhash_AI.save_score(new_boardhash,eval,depth-1,False)#評価値と盤面の対応を保存
            #print("score:",eval)
            if other_score:
                other_scores[move_string] = eval

                #transposition_table[boardhash] = eval
            if eval > max_eval:
                max_eval = eval
                best_move = move_string
            alpha = max(alpha, eval)  # αを更新
            if beta <= alpha:  # αβ枝刈り
                break
        if other_score:
            return max_eval,best_move,other_scores
        return max_eval,best_move
    else:
        #print("aFalse")
        legal_list=get_legal_square("black",board_w,board_b)
        #legal_list = sorted(legal_list,key=lambda x:new_board_and_eval(x,board1.copy(),"black"),reverse=False)
        min_eval = float('inf')
        best_move = None
        #evals = []
        evals_c = []
        if legal_list == []:
            return minimax(board_w,board_b,depth-1,alpha,beta,True,boardhash)

        for move in legal_list:
            move_string = convert_act_bit2str(move)
            #print(move_string)
            #print("move",move_string)
            #print("depth",depth)
            #print("mae",board1)
            if depth == 1:
                index = move[0]*8 + move[1]
                eval_list = predict.predict_minimax(board_w,board_b)
                eval = eval_list[index]
                return eval,None
            
            
            new_board_w,new_board_b,flip_list = identify_flip_stone("black",board_w,board_b,move_string,mode=2)
            #print(a)
            
            #print("new",new_board)
            new_boardhash = zobristhash_AI.update_hash(boardhash,move[0],move[1],0,-1)#新たに置かれた石の処理
            for flip in flip_list:
                new_boardhash = zobristhash_AI.update_hash(new_boardhash,flip[0],flip[1],1,-1)#ひっくり返る石の処理
            eval = zobristhash_AI.get_saved_score(new_boardhash,depth-1,True)
            if eval != None:
                pass
                #print("既出や1")
            else:
                new_board_90_w,new_board_90_b = rotate90(board_w),rotate90(board_b)
                boardhash_90 = zobristhash_AI.compute_hash(new_board_90_w,new_board_90_b)
                eval = zobristhash_AI.get_saved_score(boardhash_90,depth-1,True)
                if eval is None:
                    new_board_180_w,new_board_180_b = rotate90(new_board_90_w),rotate90(new_board_90_b)
                    boardhash_180 = zobristhash_AI.compute_hash(new_board_180_w,new_board_180_b)
                    eval = zobristhash_AI.get_saved_score(boardhash_180,depth-1,True)
                    if eval is None:
                        new_board_270_w,new_board_270_b = rotate90(new_board_180_w),rotate90(new_board_180_b)
                        boardhash_270 = zobristhash_AI.compute_hash(new_board_270_w,new_board_270_b)
                        eval = zobristhash_AI.get_saved_score(boardhash_270,depth-1,True)
                        if eval is None:
                            #if eval == float('inf') or eval == float('-inf'):
                            #    print(eval)
                            #    print(new_board)
                            #    print(depth-1)
                            eval ,_ = minimax_useAI(new_board_w,new_board_b,depth-1,alpha, beta,True,new_boardhash)
                            if eval == None:
                                index = move[0]*8 + move[1]
                                eval_list = predict.predict_minimax(board_w,board_b)
                                eval = eval_list[index]
                                return eval,None
                            zobristhash_AI.save_score(new_boardhash,eval,depth-1,True)#評価値と盤面の対応を保存
            if other_score:
                other_scores[move_string] = eval
                #transposition_table[boardhash] = eval
            #evals.append(eval)
            if eval < min_eval:
                min_eval = eval
                best_move = move_string
            beta = min(beta, eval)  # αを更新
            if beta <= alpha:  # αβ枝刈り
                break
        #if min_eval == float("inf"):
            #print("min")
            #print(min_eval)
            #print(evals)
            #print(evals_c)
            #print(legal_list)
        if other_score:
            return min_eval,best_move,other_scores
        return min_eval,best_move



def board_to_bitboard(board, player):
    """ 
    NumPy の 8×8 盤面をビットボードに変換する。
    - board: 8×8 の NumPy 配列（0: 空白, -1: 黒, 1: 白）
    - player: -1 (黒) または 1 (白) を指定
    - 右下 (7,7) を 最下位ビット とする
    """
    bitboard = 0
    for row in range(8):
        for col in range(8):
            if board[row, col] == player:
                index = (7 - row) * 8 + (7 - col)  # 右下を LSB にする
                bitboard |= 1 << index
    return bitboard

def bitboard_to_numpy(bitboard_w, bitboard_b):
    # 64ビット整数をリストに変換して白を1、黒を-1に変換
    board = np.zeros(64, dtype=int)  # 初期化: 0は空白
    board_w = [((bitboard_w >> i) & 1) for i in range(64)]
    board_b = [((bitboard_b >> i) & 1) for i in range(64)]
    
    for i in range(64):
        if board_w[i]:
            board[63-i] = 1  # 白は1
        elif board_b[i]:
            board[63-i] = -1  # 黒は-1

    # リストを8x8のnumpy配列に変換
    board_2d = np.array(board, dtype=int).reshape(8, 8)
    return board_2d





if __name__ == "__main__":
    pass