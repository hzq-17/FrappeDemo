/* 大屏前端资源入口（bench build 会把它打包成
 *   /assets/user_growth/dist/js/user_growth.bundle.js
 * 各模块都是"纯脚本 + 全局命名空间"，因此既可以通过 bundle 一次性加载，
 * 也可以在 bundle 缺失时按顺序直接引入单个文件（见 page/growth_dashboard/growth_dashboard.js 的兜底逻辑）。
 */
import "./growth_screen/format.js";
import "./growth_screen/api.js";
import "./growth_screen/charts.js";
import "./growth_screen/layout.js";
import "./growth_screen/screen.js";

