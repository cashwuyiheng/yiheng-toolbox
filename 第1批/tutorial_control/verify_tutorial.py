# -*- coding: utf-8 -*-
"""
tutorial.pdf 交叉验证脚本（Python 版）
用 sympy 复现 MATLAB 里的符号推导，用 scipy 做数值验证，
并生成 SVG 图（不依赖 matplotlib）。
"""
import math
import sympy as sp
from scipy.integrate import solve_ivp

OUT = r".\tutorial_control"

print("=" * 60)
print(" Part 1  Q1 质量-弹簧系统 (m=2, k=8)")
print("=" * 60)

t, s = sp.symbols('t s', real=True)
m, k = 2, 8
wn = sp.sqrt(sp.Rational(k, m))
print(f"wn = sqrt(k/m) = {wn} rad/s,  f_n = {sp.nsimplify(wn/(2*sp.pi))} Hz")

# (a) 建模：dsolve 直接解 m x'' + k x = F(t)  ——验证建模正确性
x = sp.Function('x')
F = sp.Function('F')
ode = sp.Eq(m * sp.diff(x(t), t, 2) + k * x(t), F(t))
print("\n[a] 通解（dsolve，符号形式）:")
sol = sp.dsolve(ode, x(t))
print("   ", str(sol).replace('\n', '\n    '))

# 零初始条件 + F(t)=1 阶跃，直接解
sol_step = sp.dsolve(ode.subs(F(t), 1), x(t), ics={x(0): 0, sp.diff(x(t), t).subs(t, 0): 0})
print("\n[a'] 零初值 + F(t)=1 N 的解:")
print("   ", sp.simplify(sol_step.rhs))
print("    展开验证 :", sp.expand_trig(sp.simplify(sol_step.rhs)))

# (b) 拉普拉斯变换
X = sp.Function('X')  # 占位
Xs, Fs = sp.symbols('X_s F_s')
eqL = sp.Eq(m * s**2 * Xs + k * Xs, Fs)
print("\n[b] 零初值下 L{x''}=s^2 X, 得:", eqL)

# (c) 传递函数
G = sp.simplify(sp.solve(eqL, Xs)[0] / Fs)
print("[c] 传递函数 G(s) =", G, " = ", sp.nsimplify(G))
print("    标准形式 G(s) =", sp.simplify(1/m / (s**2 + k/m)))
print("    极点  :", sp.solve(sp.denom(G), s), " → 全在虚轴，zeta = 0（临界稳定）")

# 阶跃响应（逆变换）
step_resp = sp.simplify(sp.inverse_laplace_transform(G / s, s, t))
print("\n[c'] 单位阶跃响应 x(t) =", step_resp)
print("     数值形式 :", sp.nsimplify(step_resp))
print("     稳态值 x_inf = 1/k =", sp.Rational(1, k))

# 数值验证
def q1_deriv(tt, y):
    return [y[1], (1.0 - k * y[0]) / m]

T = 6.0
tt = [T * i / 1200 for i in range(1201)]
num = solve_ivp(q1_deriv, [0, T], [0.0, 0.0], t_eval=tt, rtol=1e-10, atol=1e-12)
ana = [float((1 / k) * (1 - sp.cos(wn * sp.Rational(round(v * 1e6), 1000000)))) for v in tt]
ana = [float(sp.Rational(1, k) * (1 - sp.cos(wn * v))) for v in tt]
err1 = max(abs(a - b) for a, b in zip(num.y[0], ana))
print(f"\n[数值验证] ode45 等价积分 vs 解析解，最大误差 = {err1:.3e} m")
print(f"           数值解 x(6s) = {num.y[0][-1]:.9f}, 解析解 = {ana[-1]:.9f}")

print()
print("=" * 60)
print(" Part 2  Q2 匀加速车辆 (v0=5, a=2)")
print("=" * 60)
v0, a = 5, 2
v = sp.Function('v')
ode2 = sp.Eq(sp.diff(v(t), t), a)
print("[a] ODE:", ode2)
Vs = v0 / s + a / s**2
print("[b] V(s) = v0/s + a/s^2 =", Vs)
vt = sp.simplify(sp.inverse_laplace_transform(Vs, s, t))
print("[c] v(t) =", vt)
vt_simple = sp.simplify(sp.expand(vt.rewrite(sp.Heaviside)))
print("    展开 :", sp.expand(vt))
v10 = sp.simplify(vt.subs(t, 10))
print(f"[d] v(10) = {v10} m/s = {float(v10)} m/s")
print("    也可直接 dsolve:", sp.dsolve(ode2, v(t), ics={v(0): v0}))

# 数值验证
num2 = solve_ivp(lambda tt, y: [a], [0, 10], [float(v0)], t_eval=[10.0])
print(f"    数值积分 v(10) = {num2.y[0][0]:.9f} m/s")

# ============================================================
#  生成 SVG 图（纯标准库，手写路径）
# ============================================================
PAD_L, PAD_R, PAD_T, PAD_B = 78, 28, 56, 62


def make_chart(path, title, subtitle, xlabel, ylabel, series, x_range, y_range,
               xticks, yticks, x_fmt="{:.0f}", y_fmt="{:.1f}"):
    W, H = 820, 460
    px0, py0 = PAD_L, H - PAD_B
    px1, py1 = W - PAD_R, PAD_T
    x0, x1 = x_range
    y0, y1 = y_range

    def sx(v):
        return px0 + (v - x0) / (x1 - x0) * (px1 - px0)

    def sy(v):
        return py0 - (v - y0) / (y1 - y0) * (py0 - py1)

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Segoe UI, Microsoft YaHei, sans-serif">')
    out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
    out.append(f'<text x="{PAD_L}" y="26" font-size="18" font-weight="600" fill="#1b1f24">{title}</text>')
    out.append(f'<text x="{PAD_L}" y="46" font-size="12.5" fill="#6b7280">{subtitle}</text>')

    # grid + ticks
    for xv in xticks:
        X = sx(xv)
        out.append(f'<line x1="{X:.1f}" y1="{py1}" x2="{X:.1f}" y2="{py0}" stroke="#eaecef" stroke-width="1"/>')
        out.append(f'<line x1="{X:.1f}" y1="{py0}" x2="{X:.1f}" y2="{py0+5}" stroke="#9aa1a9" stroke-width="1"/>')
        out.append(f'<text x="{X:.1f}" y="{py0+20}" font-size="11.5" fill="#4b5563" text-anchor="middle">{x_fmt.format(xv)}</text>')
    for yv in yticks:
        Y = sy(yv)
        out.append(f'<line x1="{px0}" y1="{Y:.1f}" x2="{px1}" y2="{Y:.1f}" stroke="#eaecef" stroke-width="1"/>')
        out.append(f'<line x1="{px0-5}" y1="{Y:.1f}" x2="{px0}" y2="{Y:.1f}" stroke="#9aa1a9" stroke-width="1"/>')
        out.append(f'<text x="{px0-10}" y="{Y+4:.1f}" font-size="11.5" fill="#4b5563" text-anchor="end">{y_fmt.format(yv)}</text>')

    # axes
    out.append(f'<line x1="{px0}" y1="{py0}" x2="{px1}" y2="{py0}" stroke="#3f4650" stroke-width="1.6"/>')
    out.append(f'<line x1="{px0}" y1="{py0}" x2="{px0}" y2="{py1}" stroke="#3f4650" stroke-width="1.6"/>')
    out.append(f'<text x="{(px0+px1)/2:.0f}" y="{H-18}" font-size="13" fill="#374151" text-anchor="middle">{xlabel}</text>')
    out.append(f'<text x="18" y="{(py0+py1)/2:.0f}" font-size="13" fill="#374151" text-anchor="middle" transform="rotate(-90 18 {(py0+py1)/2:.0f})">{ylabel}</text>')

    # series
    for ser in series:
        pts = [(sx(px), sy(py)) for px, py in zip(ser["x"], ser["y"])]
        if ser.get("clip"):
            pts = [(min(max(X, px0), px1), min(max(Y, py1), py0)) for X, Y in pts]
        d = "M " + " L ".join(f"{X:.2f},{Y:.2f}" for X, Y in pts)
        dash = f' stroke-dasharray="{ser["dash"]}"' if ser.get("dash") else ""
        out.append(f'<path d="{d}" fill="none" stroke="{ser["color"]}" stroke-width="{ser.get("width",2.2)}" stroke-linejoin="round" stroke-linecap="round"{dash}/>')

    # legend
    lx, ly = px0 + 16, py1 + 14
    for i, ser in enumerate(series):
        yy = ly + i * 21
        dash = f' stroke-dasharray="{ser["dash"]}"' if ser.get("dash") else ""
        out.append(f'<line x1="{lx}" y1="{yy}" x2="{lx+26}" y2="{yy}" stroke="{ser["color"]}" stroke-width="{ser.get("width",2.2)}"{dash}/>')
        out.append(f'<text x="{lx+34}" y="{yy+4.5}" font-size="12.5" fill="#374151">{ser["label"]}</text>')

    out.append('</svg>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("已写出:", path)


# 采样解析解
N = 601
xs = [6.0 * i / (N - 1) for i in range(N)]
ys_ana = [float(sp.Rational(1, k) * (1 - sp.cos(wn * v))) for v in xs]
ys_num = list(num.y[0])[::2][:N]

make_chart(
    path=OUT + r"\q1_step_response.svg",
    title="Q1  无阻尼质量-弹簧系统的阶跃响应",
    subtitle="m = 2 kg,  k = 8 N/m,  wn = 2 rad/s,  F(t) = 1 N (阶跃),  x(t) = (1/8)(1 - cos 2t)",
    xlabel="时间 t  (s)", ylabel="位移 x  (m)",
    series=[
        {"x": xs, "y": ys_ana, "color": "#d92b2b", "label": "解析解  x(t) = (1/8)(1 - cos 2t)"},
        {"x": xs, "y": ys_num, "color": "#2b4fd9", "dash": "7 5", "width": 1.7, "label": "数值积分 (ode45 等价)"},
    ],
    x_range=(0, 6), y_range=(-0.02, 0.28),
    xticks=[0, 1, 2, 3, 4, 5, 6], yticks=[0, 0.05, 0.1, 0.15, 0.2, 0.25],
    x_fmt="{:.0f}", y_fmt="{:.2f}",
)

xs2 = [10.0 * i / (N - 1) for i in range(N)]
ys2 = [5 + 2 * v for v in xs2]

make_chart(
    path=OUT + r"\q2_velocity.svg",
    title="Q2  匀加速车辆的 v-t 图",
    subtitle="v0 = 5 m/s,  a = 2 m/s²,  v(t) = 5 + 2t,  v(10) = 25 m/s",
    xlabel="时间 t  (s)", ylabel="速度 v  (m/s)",
    series=[
        {"x": xs2, "y": ys2, "color": "#15803d", "label": "解析解  v(t) = 5 + 2t"},
        {"x": [10.0], "y": [25.0], "color": "#15803d", "label": "t = 10 s  →  v = 25 m/s"},
    ],
    x_range=(0, 10), y_range=(0, 30),
    xticks=[0, 2, 4, 6, 8, 10], yticks=[0, 5, 10, 15, 20, 25, 30],
    x_fmt="{:.0f}", y_fmt="{:.0f}",
)

print("\n全部验证完成。")
