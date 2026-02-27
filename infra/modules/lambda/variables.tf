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
  type        = string
  description = "Directory containing handler.py"
}

variable "handler" {
  type = string
}

variable "runtime" {
  type = string
}

variable "environment" {
  type    = map(string)
  default = {}
}

variable "timeout" {
  type    = number
  default = 10
}

variable "memory_size" {
  type    = number
  default = 256
}

