import pickle
from tqdm import tqdm
from parameters import *
import numpy as np
import scipy.spatial.distance
from evaluation import evaluation
from typing import *
from data_utils import _UNK_, _PAD_, _ROOT_, _NUM_
from copy import deepcopy


with open(deprel2id_path, 'rb') as fin:
    deprel2id = pickle.load(fin)
with open(arg2id_path, 'rb') as fin:
    arg2id = pickle.load(fin)
with open(arghead2id_path, 'rb') as fin:
    arghead2id = pickle.load(fin)
with open(pos2id_path, 'rb') as fin:
    pos2id = pickle.load(fin)


class Cluster:
    BETA = 0
    GAMMA = 0
    def __init__(self, data: List[Tuple[str,str,str]]) -> None:
        self.data = data
        self.lex = np.array([0] * len(arghead2id))
        self.pos = np.array([0] * len(pos2id))
    def pos_sim(self, other) -> float:
        return 1 - scipy.spatial.distance.cosine(self.pos, other.pos)
    def lex_sim(self, other) -> float:
        if abs(sum(self.lex)) < 0.00001:
            return 0.5
        elif abs(sum(other.lex)) < 0.00001:
            return 0.5
        return 1 - scipy.spatial.distance.cosine(self.lex, other.lex)
    def cons_sim(self, other) -> float:
        viol = 0
        i, j, i_, j_ = 0, 0, 0, 0
        while i < len(self.data) and j < len(other.data):
            viol += int(self.data[i][0] == other.data[j][0] and self.data[i][1] == other.data[j][1])
            i_ = int(self.data[i][0] <= other.data[j][0] or self.data[i][1] <= other.data[j][1])
            j_ = int(self.data[i][0] >= other.data[j][0] and self.data[i][1] >= other.data[j][1])
            i += i_
            j += j_
        return 1 - 2 * viol / (len(self.data) + len(other.data))
    def score(self, other) -> float:
        """ calculate the similarity between two clusters
        """
        if len(self) == 0 or len(other) == 0:
            return 1
        if self.pos_sim(other) < Cluster.BETA:
            return 0
        elif self.cons_sim(other) < Cluster.GAMMA:
            return 0
        return self.lex_sim(other)
    def __iadd__(self, other):
        self.data += other.data
        self.data.sort()
        self.lex += other.lex
        self.pos += other.pos
        return self
    def __len__(self):
        return len(self.data)
    def append(self, value, pos, arghead):
        self.data.append(value)
        if arghead in arghead2id:
            self.lex[arghead2id[arghead]] += 1
        #else:
            #print("warning")
            # self.lex[arghead2id[_UNK_]] += 1
        self.pos[pos2id[pos]] += 1
    def __iter__(self):
        return self.data.__iter__()


init_key_dict = {(deprel, verbvoice, rela_position) :Cluster([])
    for deprel in deprel2id.keys()
    for verbvoice in ['a', 'p']
    for rela_position in ['l', 'r']}
init_arg_dict = {arg:[] for arg in arg2id.keys()}


def split_phase(flattened_data_path):
    groundtruths = dict()
    predicts = dict()
    sentences = []
    with open(flattened_data_path, 'r') as fin:
        sentences = fin.readlines()

    sentence = []
    predicate = None
    predicate_id = -1
    for line in tqdm(sentences):
        word_info = line.strip().split()
        if len(word_info) == 0:
            if predicate is not None:
                for word_info in sentence:
                    if word_info[-1] != '_':
                        rela_position = 'r' if int(word_info[4]) > predicate_id else 'l'
                        verbvoice = 'p' if sentence[predicate_id-1][8] == 'VBN' else 'a'
                        deprel = word_info[12]
                        arg = word_info[14]
                        idx = (int(word_info[0]),int(word_info[1]),int(word_info[4]))
                        groundtruths[predicate][arg].append(idx)
                        predicts[predicate][(deprel,verbvoice,rela_position)].append(idx,word_info[8],sentence[int(word_info[10])-1][6])
            sentence = []
            predicate = None
            predicate_id = -1
        else:
            if word_info[3] == '1' and 'V' == word_info[8][0]:
                predicate = word_info[6]
                predicate_id = int(word_info[4])
                if predicate not in groundtruths:
                    groundtruths[predicate] = deepcopy(init_arg_dict)
                    predicts[predicate] = deepcopy(init_key_dict)
            sentence.append(word_info)
    assert(len(sentence)==0 and predicate is None)
    return groundtruths, predicts

def merge_phases(predicts: Dict[str, Dict[Any, Any]], alpha: float) -> Dict[str, Dict[Any, Any]]:
    print("=== merging ===")

    no_zero_predicts = dict()
    for word in predicts.keys():
        no_zero_predicts[word] = []
        for key in predicts[word].keys():
            if len(predicts[word][key]) != 0:
                no_zero_predicts[word].append(predicts[word][key])
        no_zero_predicts[word].sort(key = len, reverse=True)

    for gamma in tqdm(np.arange(0.95, 0, -0.05)):
        Cluster.GAMMA = gamma
        for beta in tqdm(np.arange(0.95, 0, -0.05)):
            Cluster.BETA = beta
            for word in no_zero_predicts.keys():
                c_i, c_j = 0, 0
                while c_i < len(no_zero_predicts[word]):
                    c_j, max_score = -1, 0
                    for j in range(c_i):
                        score = no_zero_predicts[word][c_i].score(no_zero_predicts[word][j])
                        if score > max_score:
                            max_score = score
                            c_j = j
                    if max_score > alpha:
                        no_zero_predicts[word][c_j] += no_zero_predicts[word][c_i]
                        del no_zero_predicts[word][c_i]
                    else:
                        c_i += 1
    
    final_predicts = dict()
    for word, clusters_list in no_zero_predicts.items():
        clusters_dict = {i: cluster for i, cluster in enumerate(clusters_list)}
        final_predicts[word] = clusters_dict
    return final_predicts


def main():
    truths, predicts = split_phase(flattened_test_data_path)
    pre, coll, f1 = evaluation(truths, predicts)
    print(pre, coll, f1)
    final_pre = merge_phases(predicts, 0.3)
    pre, coll, f1 = evaluation(truths, final_pre)
    print(pre, coll, f1)

    # 1. combine all those verb's clusters together and calculate new result
    # truths_combine = {'combine': init_arg_dict.copy()}
    # predicts_combine = {'combine': init_key_dict.copy()}
    # for word in truths:
    #     for key in truths[word].keys():
    #         truths_combine['combine'][key] = truths_combine['combine'][key] | truths[word][key]
    # for word in predicts:
    #     for key in predicts[word].keys():
    #         predicts_combine['combine'][key] = predicts_combine['combine'][key] | predicts[word][key]
    # pre, coll, _, _ = eval_f1(truths_combine, predicts_combine)
    # print(pre, coll)

if __name__ == "__main__":
    main()
