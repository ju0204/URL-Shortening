variable "project_name" {
  type = string
}

variable "function_name" {
  type = string
}

variable "role_arn" {
  type = string
}

variable "source_dir" {
  type = string
}

variable "handler" {
  type = string
}

variable "runtime" {
  type = string
}

variable "timeout" {
  type    = number
  default = 60
}

variable "memory_size" {
  type    = number
  default = 512
}

variable "environment" {
  type    = map(string)
  default = {}
}
