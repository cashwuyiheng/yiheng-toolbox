%% ============================================================
%  Tutorial 详解脚本
%  题面：tutorial.pdf（无阻尼质量-弹簧系统 / 匀加速车辆）
%
%  用 MATLAB 完成整条链路：
%    牛顿第二定律建模 -> 拉普拉斯变换 -> 传递函数
%    -> 逆变换 -> 数值验证（ode45）-> 画图
%
%  运行方式：在 MATLAB 中打开本文件按 F5，或命令行输入
%            >> tutorial_solve
%
%  说明：符号部分需要 Symbolic Math Toolbox；
%        若未安装，脚本会自动跳过符号段，只跑数值验证。
%        最后一段（波特图）需要 Control System Toolbox，可选。
% ============================================================

clear; close all; clc;

wd = fileparts(mfilename('fullpath'));
if isempty(wd), wd = pwd; end

fprintf('==============================================\n');
fprintf(' Part 0  环境检查\n');
fprintf('==============================================\n');
fprintf('MATLAB 版本 : %s\n', version);
haveSym = ~isempty(ver('symbolic')) && license('test','Symbolic_Toolbox');
haveCtrl = ~isempty(ver('control')) && license('test','Control_Toolbox');
fprintf('Symbolic Toolbox : %s\n', string(haveSym));
fprintf('Control  Toolbox : %s\n', string(haveCtrl));
fprintf('\n');

%% ============================================================
%  Question 1: m = 2 kg, k = 8 N/m 的无阻尼质量-弹簧系统
%  ============================================================
m = 2;                      % kg
k = 8;                      % N/m
wn = sqrt(k/m);             % 固有频率 rad/s
fn = wn/(2*pi);             % Hz

fprintf('==============================================\n');
fprintf(' Question 1  无阻尼质量-弹簧系统\n');
fprintf('==============================================\n');
fprintf(' m = %g kg,  k = %g N/m\n', m, k);
fprintf(' 固有频率 wn = sqrt(k/m) = %g rad/s = %g Hz\n\n', wn, fn);

% ---------- (a) 建模 ----------
% 牛顿第二定律：合力 = 质量 x 加速度
%   外力 F(t) 向右为正，弹簧恢复力 -k*x 向左，无阻尼项
%   =>  m*x''(t) + k*x(t) = F(t)
fprintf('[a] 微分方程（牛顿第二定律 sum F = m*a）：\n');
fprintf('      m * x''''(t) + k * x(t) = F(t)\n');
fprintf('      %g * x''''(t) + %g * x(t) = F(t)\n', m, k);
fprintf('  整理成标准形式：\n');
fprintf('      x''''(t) + (k/m) * x(t) = (1/m) * F(t)\n');
fprintf('      x''''(t) + %g * x(t) = %g * F(t)\n\n', k/m, 1/m);

% ---------- (b) 拉普拉斯变换（零初始条件） ----------
% L{x''(t)} = s^2 X(s) - s x(0) - x'(0)
% 零初始条件 x(0) = 0, x'(0) = 0  =>  L{x''(t)} = s^2 X(s)
% L{x(t)} = X(s),  L{F(t)} = F(s)
% => m s^2 X(s) + k X(s) = F(s)
fprintf('[b] 拉普拉斯变换（x(0)=0, x''(0)=0）：\n');
fprintf('      L{x''''(t)} = s^2 * X(s)\n');
fprintf('      %g * s^2 * X(s) + %g * X(s) = F(s)\n', m, k);
fprintf('      (%g s^2 + %g) * X(s) = F(s)\n\n', m, k);

% ---------- (c) 传递函数 ----------
% G(s) = X(s)/F(s) = 1 / (m s^2 + k)
if haveSym
    syms s X Fs
    eqL   = m*s^2*X + k*X == Fs;      % (b) 的代数方程
    Xsol  = solve(eqL, X);            % X(s) = F(s)/(m s^2 + k)
    Gsym  = simplify(Xsol/Fs);        % 传递函数
    Xstep = simplify(ilaplace(Gsym*(1/s), s, sym('t')));  % 单位阶跃响应

    fprintf('[c] 传递函数：\n');
    fprintf('      G(s) = X(s)/F(s) = 1 / (m s^2 + k)\n');
    fprintf('      G(s) = %s\n', char(Gsym));
    fprintf('      G(s) = 1 / (%g (s^2 + %g)) = %g / (s^2 + %g)\n\n', ...
            m, k/m, 1/m, k/m);

    fprintf('  补充：极点与阻尼\n');
    fprintf('      特征方程 m s^2 + k = 0  =>  s = +/- j*sqrt(k/m) = +/- %g j\n', wn);
    fprintf('      极点全在虚轴上，阻尼比 zeta = 0，系统临界稳定（等幅振荡）\n');
    fprintf('      单位阶跃响应 x(t) = %s\n\n', char(Xstep));
else
    fprintf('[c] G(s) = 1/(%g s^2 + %g) = %g/(s^2 + %g)   (符号工具箱缺失，手写结论)\n\n', ...
            m, k, 1/m, k/m);
end

%% ============================================================
%  Question 2: v_i = 5 m/s, a = 2 m/s^2 的匀加速直线运动
%  ============================================================
v0 = 5;                     % m/s
a  = 2;                     % m/s^2

fprintf('==============================================\n');
fprintf(' Question 2  匀加速直线运动\n');
fprintf('==============================================\n');
fprintf(' v(0) = %g m/s,  a = %g m/s^2\n\n', v0, a);

% ---------- (a) 建模 ----------
% 加速度 = 速度对时间的导数：dv/dt = a
fprintf('[a] 微分方程：\n');
fprintf('      dv/dt = a(t)          （这里 a 为常数 %g）\n\n', a);

% ---------- (b) 拉普拉斯变换 ----------
% L{v'(t)} = s V(s) - v(0)
% => s V(s) - v(0) = a/s
% => V(s) = v(0)/s + a/s^2
fprintf('[b] 拉普拉斯变换（v(0)=%g）：\n', v0);
fprintf('      s * V(s) - v(0) = a/s\n');
fprintf('      V(s) = v(0)/s + a/s^2 = %g/s + %g/s^2\n\n', v0, a);

% ---------- (c) 逆变换 ----------
% L^-1{1/s} = 1,  L^-1{1/s^2} = t
% => v(t) = v(0) + a t
fprintf('[c] 逆拉普拉斯变换：\n');
fprintf('      v(t) = L^-1{v(0)/s + a/s^2} = v(0) + a*t = %g + %g t   [m/s]\n\n', v0, a);

% ---------- (d) t = 10 s ----------
t10 = 10;
v10 = v0 + a*t10;
fprintf('[d] t = %g s 时的速度：\n', t10);
fprintf('      v(%g) = %g + %g*%g = %g m/s\n\n', t10, v0, a, t10, v10);

if haveSym
    syms s t V real
    Vs = v0/s + a/s^2;
    vt = simplify(ilaplace(Vs, s, t));
    fprintf('  符号校验：ilaplace 得到 v(t) = %s\n', char(vt));
    fprintf('            在 t=10 处代入得 %.4f m/s\n\n', double(subs(vt, t, t10)));
end

%% ============================================================
%  Part 3  数值验证：符号解 vs ode45 数值解
%  ============================================================
fprintf('==============================================\n');
fprintf(' Part 3  数值验证（符号解 vs ode45）\n');
fprintf('==============================================\n');

% ---- Q1：输入取单位阶跃力 F(t) = 1 N ----
Fstep = 1;
ode1  = @(t,x) [x(2); (Fstep - k*x(1))/m];      % x1 = x, x2 = x'
opts  = odeset('RelTol',1e-10,'AbsTol',1e-12);
ts    = linspace(0, 6, 1201);
[t_num, x_num] = ode45(ode1, ts, [0;0], opts);
x_fun = (1/k)*(1 - cos(wn*ts));                  % 解析解
err1  = max(abs(x_num(:,1) - x_fun.'));
fprintf(' Q1 单位阶跃力 F=1 N\n');
fprintf('    解析解 x(t) = (1/k)(1 - cos(wn t)) = %g (1 - cos(%g t))\n', 1/k, wn);
fprintf('    稳态位移 x_inf = F/k = %g m，振荡幅度 = %g m\n', Fstep/k, Fstep/k);
fprintf('    ode45 与解析解最大误差 = %.3e m\n\n', err1);

% ---- Q2：数值积分 ----
ode2 = @(t,v) a;
[t2, v2] = ode45(ode2, [0 10], v0);
v2_exact = v0 + a*t2;
err2 = max(abs(v2 - v2_exact));
fprintf(' Q2 数值解与解析解最大误差 = %.3e m/s\n', err2);
fprintf('    数值解 v(10) = %.6f m/s，解析解 = %.6f m/s\n\n', v2(end), v10);

%% ============================================================
%  Part 4  画图
%  ============================================================
fprintf(' Part 4  绘图 ...\n');

figure('Name','Q1 质量-弹簧系统','Color','w');
plot(ts, x_fun, 'LineWidth', 2, 'Color', [0.85 0.2 0.2]); hold on;
plot(t_num, x_num(:,1), '--', 'LineWidth', 1.4, 'Color', [0.15 0.25 0.75]);
yline(Fstep/k, ':', '稳态 F/k', 'Color', [0.4 0.4 0.4]);
grid on; xlabel('t  (s)'); ylabel('位移 x  (m)');
title(sprintf('Q1 阶跃响应：无阻尼振荡（wn = %g rad/s）', wn));
legend('解析解','ode45 数值解','Location','southeast');
exportgraphics(gcf, fullfile(wd,'q1_step_response.png'), 'Resolution', 160);

figure('Name','Q2 匀加速车辆','Color','w');
plot(ts, v0 + a*ts, 'LineWidth', 2, 'Color', [0.1 0.5 0.3]); hold on;
plot(t2, v2, '--', 'LineWidth', 1.4, 'Color', [0.9 0.5 0.1]);
plot(10, v10, 'ko', 'MarkerSize', 9, 'MarkerFaceColor', 'k');
text(10, v10, sprintf('  v(10)=%g m/s', v10), 'VerticalAlignment','bottom');
grid on; xlabel('t  (s)'); ylabel('速度 v  (m/s)');
title('Q2 匀加速运动：v(t) = 5 + 2t');
legend('解析解','ode45 数值解','t = 10 s','Location','northwest');
exportgraphics(gcf, fullfile(wd,'q2_velocity.png'), 'Resolution', 160);

% ---- 可选：Q1 波特图与极点零点（需要 Control System Toolbox） ----
if haveCtrl
    try
        Gq1 = tf(1, [m 0 k]);           % 1/(2 s^2 + 8)
        figure('Name','Q1 频率特性','Color','w');
        bode(Gq1); grid on;
        title('Q1  传递函数 G(s) = 1/(2s^2 + 8) 的波特图');
        exportgraphics(gcf, fullfile(wd,'q1_bode.png'), 'Resolution', 160);

        figure('Name','Q1 极点零点','Color','w');
        pzmap(Gq1); grid on;
        title('Q1  极点位于虚轴 +/-2j（临界稳定）');
        exportgraphics(gcf, fullfile(wd,'q1_pzmap.png'), 'Resolution', 160);
    catch ME
        fprintf('  波特图绘制跳过：%s\n', ME.message);
    end
else
    fprintf('  未检测到 Control System Toolbox，跳过滤波器图。\n');
end

fprintf('\n全部完成。图片已输出到：%s\n', wd);
