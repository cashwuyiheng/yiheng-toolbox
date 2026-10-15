# Tutorial Solutions — 中英穿插版

> 原题：桌面 `tutorial.pdf`
> 排版：英文一句，中文一句，公式两种语言共用。

---

## Question 1 — Undamped mass–spring system ｜ 无阻尼质量-弹簧系统

**Problem ｜ 题干**

Consider an undamped mass–spring system with mass m = 2 kg and spring stiffness k = 8 N/m. An external force F(t) is applied to the mass, and the displacement x(t) is measured.
考虑一个无阻尼质量-弹簧系统，质量 m = 2 kg，弹簧刚度 k = 8 N/m；外力 F(t) 施加在质量块上，观测的物理量是位移 x(t)。

a) Derive the differential equation describing the motion of the mass.
a) 推导描述质量块运动的微分方程。

b) Assuming zero initial conditions, take the Laplace transform of the differential equation.
b) 假设初始条件为零，对微分方程作拉普拉斯变换。

c) Determine the transfer function G(s) = X(s)/F(s).
c) 求传递函数 G(s) = X(s)/F(s)。

**Solution ｜ 解答**

**(a) Differential equation ｜ 微分方程**

Take the equilibrium position, where the spring is at its natural length, as the origin, with x measured positive in the direction of the applied force F(t).
取弹簧自然长度处为原点（即平衡位置），x 沿外力 F(t) 的方向为正。

The mass is subject to two horizontal forces: the applied force F(t) acting in the positive direction, and the spring restoring force −k·x(t), which follows Hooke's law and always acts toward the equilibrium position.
质点水平方向只受两个力：沿正方向的外力 F(t)，以及弹簧恢复力 −k·x(t)；后者由胡克定律给出，方向始终指向平衡位置。

Newton's second law states ΣF = m·a, where a = x''(t):
由牛顿第二定律，ΣF = m·a，其中 a = x''(t)：

```
m·x''(t) = F(t) − k·x(t)
```

Rearranging gives the equation of motion:
移项即得运动方程：

```
m·x''(t) + k·x(t) = F(t)
```

Substituting m = 2 kg and k = 8 N/m:
代入 m = 2 kg、k = 8 N/m：

```
2·x''(t) + 8·x(t) = F(t)

or equivalently ｜ 等价于

x''(t) + 4·x(t) = 0.5·F(t)
```

**(b) Laplace transform with zero initial conditions ｜ 零初始条件下的拉普拉斯变换**

With x(0) = 0 and x'(0) = 0, the differentiation property gives
因 x(0) = 0、x'(0) = 0，由微分性质可得

```
L{x''(t)} = s²X(s) − s·x(0) − x'(0) = s²X(s)
```

Taking the Laplace transform of both sides of the equation of motion:
对方程两边取拉普拉斯变换：

```
m·s²X(s) + k·X(s) = F(s)
```

Collecting the terms in X(s):
合并含 X(s) 的项：

```
(m·s² + k)·X(s) = F(s)

2s²X(s) + 8X(s) = F(s)
```

**(c) Transfer function ｜ 传递函数**

Solving for the ratio X(s)/F(s):
解出比值 X(s)/F(s)：

```
G(s) = X(s)/F(s) = 1/(m·s² + k) = 1/(2s² + 8) = 0.5/(s² + 4)
```

In standard second-order form:
写成标准二阶形式：

```
G(s) = (1/m)/(s² + ω_n²),   ω_n = sqrt(k/m) = 2 rad/s
```

The characteristic equation 2s² + 8 = 0 gives a pair of poles at s = ±2j, i.e. on the imaginary axis.
特征方程 2s² + 8 = 0 给出一对极点 s = ±2j，即落在虚轴上。

The damping ratio is therefore ζ = 0, so the system is marginally stable (critically stable), and its step response oscillates with constant amplitude.
因此阻尼比 ζ = 0，系统为临界稳定（无阻尼），其阶跃响应为等幅振荡，既不衰减也不发散。

---

## Question 2 — Vehicle with constant acceleration ｜ 匀加速直线运动的车辆

**Problem ｜ 题干**

A vehicle moves along a straight line with constant acceleration. Its initial velocity is v_i = 5 m/s, and its acceleration is a = 2 m/s².
一辆车沿直线作匀加速运动，初速度 v_i = 5 m/s，加速度 a = 2 m/s²。

a) Write the differential equation relating velocity v(t) and acceleration a(t).
a) 写出联系速度 v(t) 与加速度 a(t) 的微分方程。

b) Using the initial condition v(0) = 5 m/s, take the Laplace transform of the differential equation to calculate V(s).
b) 利用初始条件 v(0) = 5 m/s，对微分方程作拉普拉斯变换，求出 V(s)。

c) Obtain the velocity v(t) using the inverse Laplace transform.
c) 用逆拉普拉斯变换求出速度 v(t)。

d) Determine the velocity of the vehicle after t = 10 seconds.
d) 求 t = 10 秒时车辆的速度。

**Solution ｜ 解答**

**(a) Differential equation ｜ 微分方程**

Acceleration is the time derivative of velocity:
加速度是速度对时间的导数：

```
dv/dt = a(t) = 2
```

**(b) Laplace transform ｜ 拉普拉斯变换**

Using the differentiation property L{v'(t)} = sV(s) − v(0):
用微分性质 L{v'(t)} = sV(s) − v(0)：

```
sV(s) − v(0) = a/s

sV(s) − 5 = 2/s
```

Solving for V(s):
解出 V(s)：

```
V(s) = 5/s + 2/s²
```

**(c) Inverse Laplace transform ｜ 逆拉普拉斯变换**

Using the basic transform pairs L⁻¹{1/s} = 1 and L⁻¹{1/s²} = t:
用基本变换对 L⁻¹{1/s} = 1、L⁻¹{1/s²} = t：

```
v(t) = 5 + 2t   [m/s]
```

This agrees with the familiar constant-acceleration formula v = v_i + a·t.
这与熟知的匀加速公式 v = v_i + a·t 一致。

**(d) Velocity at t = 10 s ｜ t = 10 s 时的速度**

```
v(10) = 5 + 2 × 10 = 25 m/s
```

---

## Key results ｜ 关键结论速查

| Item ｜ 项目 | Result ｜ 结果 |
|---|---|---|
| Q1 equation of motion ｜ 运动方程 | m·x'' + k·x = F, i.e. 2x'' + 8x = F |
| Q1 algebraic equation in s ｜ s 域代数方程 | (2s² + 8)·X(s) = F(s) |
| Q1 transfer function ｜ 传递函数 | G(s) = 1/(2s² + 8) = 0.5/(s² + 4) |
| Q1 poles / damping ｜ 极点与阻尼 | s = ±2j, ζ = 0, marginally stable ｜ 临界稳定 |
| Q1 natural frequency ｜ 固有频率 | ω_n = 2 rad/s |
| Q2 differential equation ｜ 微分方程 | dv/dt = 2 |
| Q2 V(s) | 5/s + 2/s² |
| Q2 velocity ｜ 速度 | v(t) = 5 + 2t m/s |
| Q2 v(10) | 25 m/s |
