# R8（full mode）规则。
#
# 为什么要 keep：Activity / 自定义 View 是由 AndroidManifest.xml 字符串引用的，
# R8 看不到任何代码级引用，不 keep 会把入口一起删掉，装上去就是点不开。
#
# 这个项目没有任何反射、没有 XML 布局（界面是纯代码搭的），
# 所以除下面两行外不需要保留任何东西 —— kotlin-stdlib 会被整棵摇掉，
# 实测 APK 与纯 Java 版同尺寸（见 README「体积」一节）。

-keep class face.tool.MainActivity { *; }
-keep class face.tool.CropView { *; }

# 框架类的引用警告噪音，不是真问题
-dontwarn **
