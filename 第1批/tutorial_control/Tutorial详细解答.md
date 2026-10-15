# Tutorial 详细解答

> 题源：`<桌面>\tutorial.pdf`（共 2 页，两道题）
> 所有公式均经符号计算（sympy）与数值积分双重验证，见文末「验证记录」。

---

## Question 1 — 无阻尼质量-弹簧系统

**已知**：质量 m = 2 kg，弹簧刚度 k = 8 N/m，外力 F(t)，位移 x(t)。

### (a) 推导运动的微分方程

取弹簧自然长度处为坐标原点，x 向拉力方向为正。质点水平方向只受两个力：

| 力 | 表达式 | 方向 |
|---|---|---|
| 外力 | F(t) | 正向 |
| 弹簧恢复力（胡克定律） | −k·x(t) | 总指向平衡位置 |

由牛顿第二定律 ΣF = m·a，且 a = x''(t)：

$$m\,\ddot{x}(t) = F(t) - k\,x(t)$$

移项，得到**运动微分方程**：

$$\boxed{\;m\,\ddot{x}(t) + k\,x(t) = F(t)\;}$$

代入数值：

$$2\,\ddot{x}(t) + 8\,x(t) = F(t) \qquad\Longleftrightarrow\qquad \ddot{x}(t) + 4\,x(t) = \tfrac{1}{2}F(t)$$

> 注：题面说「无阻尼」，所以没有 c·x'(t) 项。若考虑阻尼，方程变为 m x'' + c x' + k x = F。

### (b) 零初始条件下的拉普拉斯变换

记 X(s) = ℒ{x(t)}，F(s) = ℒ{F(t)}。用**微分性质**：

$$\mathcal{L}\{x'(t)\} = sX(s) - x(0)$$
$$\mathcal{L}\{x''(t)\} = s^2X(s) - s\,x(0) - x'(0)$$

零初始条件 x(0) = 0，x'(0) = 0，于是 ℒ{x''(t)} = s²X(s)。

ℒ 是线性算子，逐项变换：

$$m\left[s^2X(s)\right] + k\,X(s) = F(s)$$

整理成**代数方程**：

$$\boxed{\;(m s^2 + k)\,X(s) = F(s)\;}\qquad\Longrightarrow\qquad (2s^2 + 8)\,X(s) = F(s)$$

### (c) 传递函数

由 (b) 直接解出：

$$\boxed{\;G(s) = \frac{X(s)}{F(s)} = \frac{1}{m s^2 + k} = \frac{1}{2s^2 + 8} = \frac{0.5}{s^2 + 4}\;}$$

写成标准二阶形式：

$$G(s) = \frac{1/m}{s^2 + \omega_n^2},\qquad \omega_n = \sqrt{\frac{k}{m}} = \sqrt{\frac{8}{2}} = 2\ \text{rad/s}$$

**物理参数与稳定性**

- 特征方程 m s² + k = 0 ⇒ **极点 s = ±2j**，位于虚轴上。
- 阻尼比 ζ = 0 ⇒ 系统**临界稳定**（无阻尼），阶跃响应为等幅振荡，既不发散也不收敛。
- 零点：无（分子是常数 1）。
- 因极点在虚轴上，**终值定理不适用**（x(∞) 不存在）。

**补充：单位阶跃响应**（取 F(t) = 1 N，即 F(s) = 1/s）

$$X(s) = \frac{1}{s(2s^2+8)} = \frac{1}{8}\left(\frac{1}{s} - \frac{s}{s^2+4}\right) \;\xrightarrow{\;\mathcal{L}^{-1}\;}\; x(t) = \frac{1}{8}\bigl(1 - \cos 2t\bigr)\ \text{m}$$

- 振荡中心（静态位移）F/k = 1/8 = 0.125 m
- 振幅 0.125 m ⇒ x 在 0 ~ 0.25 m 之间来回振荡
- 周期 T = 2π/ωn = π ≈ 3.14 s

---

## Question 2 — 匀加速直线运动

**已知**：初速度 v_i = 5 m/s，加速度 a = 2 m/s²。

### (a) 写出微分方程

加速度就是速度对时间的导数：

$$\boxed{\;\frac{dv}{dt} = a(t) = 2\;}$$

（若以位移 x 描述，则是二阶方程 d²x/dt² = a；这里题面直接给了 v(t) 与 a(t)，用一阶方程即可。）

### (b) 拉普拉斯变换求 V(s)

用微分性质 ℒ{v'(t)} = sV(s) − v(0)，两边取变换：

$$sV(s) - v(0) = \frac{a}{s}\Big|_{\text{常数 }a=2}$$

代入 v(0) = 5，a = 2：

$$sV(s) - 5 = \frac{2}{s} \qquad\Longrightarrow\qquad \boxed{\;V(s) = \frac{5}{s} + \frac{2}{s^{2}}\;}$$

### (c) 逆拉普拉斯变换求 v(t)

用两条基本变换对 ℒ⁻¹{1/s} = 1，ℒ⁻¹{1/s²} = t（t ≥ 0）：

$$v(t) = \mathcal{L}^{-1}\!\left\{\frac{5}{s} + \frac{2}{s^2}\right\} = 5 + 2t \quad \text{[m/s]}$$

与匀加速公式 v = v_i + a·t 完全一致。

### (d) t = 10 s 时的速度

$$v(10) = 5 + 2 \times 10 = \boxed{25\ \text{m/s}}$$

---

## 在 MATLAB 里怎么做

脚本：**`tutorial_solve.m`**（与本文档同目录）

### 运行方法

1. 把 `tutorial_solve.m` 放到任意文件夹（比如桌面）
2. 在 MATLAB 里打开它，按 <kbd>F5</kbd>，或命令行输入 `tutorial_solve`
3. 命令行会打印全部推导结果，并输出四张图：`q1_step_response.png`、`q2_velocity.png`（+ 可选 `q1_bode.png`、`q1_pzmap.png`）

### 脚本用到的 MATLAB 功能

| 环节 | 函数 | 所属工具箱 |
|---|---|---|
| 符号变量与方程 | `syms`, `solve` | Symbolic Math Toolbox |
| 拉普拉斯逆变换 | `ilaplace` | Symbolic Math Toolbox |
| 解微分方程（可选） | `dsolve` | Symbolic Math Toolbox |
| 数值求解 | `ode45`, `odeset` | 基础 MATLAB |
| 传递函数、波特图 | `tf`, `bode`, `pzmap` | Control System Toolbox（可选） |
| 出图 | `plot`, `exportgraphics` | 基础 MATLAB |

脚本开头会打印工具箱检测结果，并且**做了降级处理**：如果没有 Symbolic / Control 工具箱，会自动跳过对应段落、只跑基础数值部分，不会报错中断。

### 核心几行（等价于手算）

```matlab
% ---------- Q1 ----------
syms s X Fs
m = 2; k = 8;
eqL  = m*s^2*X + k*X == Fs;      % (b) 的代数方程
G    = simplify(solve(eqL,X)/Fs) % (c) 传递函数 → 1/(2 s^2 + 8)
xstep = ilaplace(G/s, s, sym('t'))  % 阶跃响应 → sin(t)^2/4

% ---------- Q2 ----------
v0 = 5; a = 2;
Vs = v0/s + a/s^2;              % (b) V(s) = 5/s + 2/s^2
vt = ilaplace(Vs, s, sym('t'))  % (c) → 2t + 5
v10 = double(subs(vt, t, 10))   % (d) → 25
```

---

## 验证记录

本次解答用 Python 的 sympy（符号）与 scipy（数值）独立复现了一遍，全部对得上：

| 检查项 | 结果 |
|---|---|
| Q1 传递函数 | `1/(2(s²+4))` = `0.5/(s²+4)` ✔ |
| Q1 阶跃响应 | `sin²(t)/4` = (1/8)(1−cos 2t) ✔ |
| Q1 ode45 数值解 vs 解析解 | 最大误差 **2.5×10⁻¹¹ m** ✔ |
| Q1 稳态静态位移 | F/k = 0.125 m ✔ |
| Q2 V(s) | `5/s + 2/s²` ✔ |
| Q2 逆变换 | `2t + 5` ✔ |
| Q2 v(10) | 25.000000000 m/s（解析）vs 25.000000000 m/s（数值积分）✔ |
