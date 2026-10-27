"""H2 test: extra TP levels. Run: python test_dual_tp_ext.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_tp_ext as X
import tag_lab as TL

ok = 0
def check(c, msg):
    global ok
    if not c:
        print("FAIL:", msg); sys.exit(1)
    ok += 1

m, sd = 100.0, 10.0
# long, entry low: bot ladder 0 / 1 / 2 / 3 SD -> extras 4, 5, 6 SD
t = X.extend([100.0, 110.0, 120.0, 130.0], 1, m, sd)
check(t == [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0], "long: 3 extra SD levels above TP4: %s" % t)
# long, entry high: bot ladder repeats 3 SD four times -> first four stay as they were, extras still go further out
t = X.extend([130.0] * 4, 1, m, sd)
check(t[:4] == [130.0] * 4 and t[4:] == [140.0, 150.0, 160.0], "long, high entry: extras go beyond 3 SD")
# short mirrors it
t = X.extend([100.0, 90.0, 80.0, 70.0], -1, m, sd)
check(t == [100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0], "short: extras go below")
# entry far below the band: ladder ends at the mean, extras are the next bands up
t = X.extend([70.0, 80.0, 90.0, 100.0], 1, m, sd)
check(t[4:] == [110.0, 120.0, 130.0], "low entry: extras continue upward")
# nothing breaks: bad input gives the original list back
check(X.extend([1, 2, 3], 1, m, sd) == [1, 2, 3], "wrong length -> unchanged")
check(X.extend([1, 2, 3, 4], 1, None, sd) == [1, 2, 3, 4], "no mean -> unchanged")
check(X.extend([1, 2, 3, 4], 1, m, 0) == [1, 2, 3, 4], "no sd -> unchanged")
check(X.extend([1, 2, 3, 4], 1, m, sd, n_extra=0) == [1, 2, 3, 4], "n_extra 0 -> unchanged")

# sim_rule: with 7 levels and cap=7 the trade keeps running past TP4; with cap=4 it closes at TP4 as before
n = 14
S = {"h": [100 + 4 * k + 1 for k in range(n)], "l": [100 + 4 * k - 1 for k in range(n)], "c": [100 + 4 * k for k in range(n)],
     "t": [1_000_000 + 300_000 * k for k in range(n)], "n": n, "xup": [False] * n, "xdn": [False] * n}
Z = {"up": [False] * n, "dn": [False] * n}
tps7 = [102.0, 106.0, 110.0, 114.0, 118.0, 122.0, 126.0]
a = TL.sim_rule(S, Z, 0, 1, 100.0, 98.0, tps7[:4], 10.0, 1.0, cap=4, be=True, xmode="main")
check(a and a["why"] == "TP" and a["hit"] == 4 and a["px"] == 114.0, "4 levels, cap 4: closes at TP4 as before")
b = TL.sim_rule(S, Z, 0, 1, 100.0, 98.0, tps7, 10.0, 1.0, cap=7, be=True, xmode="main")
check(b and b["why"] == "TP" and b["hit"] == 7 and b["px"] == 126.0, "7 levels, cap 7: stays open to TP7")
c = TL.sim_rule(S, Z, 0, 1, 100.0, 98.0, tps7, 10.0, 1.0, cap=4, be=True, xmode="main")
check(c and c["px"] == 114.0, "cap 4 with 7 levels still closes at TP4")
print("test_dual_tp_ext: %d checks passed" % ok)
