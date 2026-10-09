<script setup lang="ts">
import { ref } from 'vue'
const v = ref(true)
</script>

<template>
  <div class="pagebg">
    <div class="card">用户管理（占位页内容）</div>
    <div class="card">表格占位</div>
    <el-dialog v-model="v" title="新增用户" width="min(480px, 94vw)" class="user-form-dialog">
      <el-form label-width="88px">
        <el-form-item label="工号" required><el-input placeholder="如 00660301" /></el-form-item>
        <el-form-item label="姓名" required><el-input placeholder="真实姓名" /></el-form-item>
        <el-form-item label="角色" required>
          <el-select style="width:100%">
            <el-option label="产线用户" value="line" /><el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="初始口令"><el-input type="password" show-password placeholder="至少 6 位" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button>取消</el-button>
        <el-button type="primary">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.pagebg { padding: 12px 16px; min-height: 100vh; }
.card { background: #fff; border: 1px solid #e6ebf2; border-radius: 14px; padding: 16px; margin-bottom: 12px; }

/* ==== 与 UserManageView.vue 完全一致的弹窗样式 ==== */
.user-form-dialog { max-width: 94vw; }
.user-form-dialog :deep(.el-dialog) {
  width: min(480px, 94vw) !important;
  max-width: 94vw !important;
  box-sizing: border-box;
}
.user-form-dialog :deep(.el-dialog__body) {
  padding: 18px 20px 6px;
  overflow: hidden;
}
.user-form-dialog :deep(.el-form) {
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}
.user-form-dialog :deep(.el-form-item) {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  margin-right: 0;
  overflow: hidden;
}
.user-form-dialog :deep(.el-form-item__label) {
  flex: 0 0 auto !important;
  width: 88px !important;
  max-width: 88px !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}
.user-form-dialog :deep(.el-form-item__content) {
  flex: 1 1 auto;
  min-width: 0;
  width: auto !important;
}
.user-form-dialog :deep(.el-input),
.user-form-dialog :deep(.el-select) {
  width: 100% !important;
  max-width: 100%;
  min-width: 0;
}
.user-form-dialog :deep(.el-form-item__label .el-form-item__error) {
  width: 100%;
  white-space: normal;
  text-overflow: clip;
}
</style>
