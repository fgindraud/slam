Screen := [wa, ha, wb, hb] -> {
[o, w, h, xa, ya, xb, yb] :
0 <= w, h <= 32000 and

0 < wa, ha, wb, hb and

0 <= xa and xa + wa <= w and
0 <= ya and ya + ha <= h and

0 <= xb and xb + wb <= w and
0 <= yb and yb + hb <= h and

(xa + wa <= xb or xb + wb <= xa or ya + ha <= yb or yb + hb <= ya) and

xa + wa <= xb and yb + hb <= ya and

o = w + h 
};

R := lexmin (Screen);

R2 := [wa, ha, wb, hb] -> { : wa = 16 and ha = 9 and wb = 19 and hb = 10 };

print (coalesce (R * R2));

