variable "project_name" {
  type = string
}

variable "urls_table_arn" {
  type = string
}

variable "clicks_table_arn" {
  type = string
}

variable "insights_table_arn" {
  type = string
}

# 필요할 때만 true로 켜서 DeleteItem 권한 포함
variable "enable_delete_item" {
  type    = bool
  default = false
}
