import { cn } from "@/lib/utils";
import {
  HelpCircle,
  Package,
  Plug,
  GitBranch,
  Code2,
  KeyRound,
  BookOpenText,
  Lightbulb,
  ShieldAlert,
  MoreHorizontal,
  LucideIcon,
} from "lucide-react";

const categoryIcons: Record<string, LucideIcon> = {
  "How-to": HelpCircle,
  Product: Package,
  Connector: Plug,
  Lineage: GitBranch,
  "API/SDK": Code2,
  SSO: KeyRound,
  Glossary: BookOpenText,
  "Best practices": Lightbulb,
  "Sensitive data": ShieldAlert,
  Other: MoreHorizontal,
};

type QuestionCardProps = {
  category: keyof typeof categoryIcons;
  question: string;
  onClick?: () => void;
  className?: string;
};

export const QuestionCard = ({ category, question, onClick, className }: QuestionCardProps) => {
  const Icon = categoryIcons[category];

  return (
    <figure
      onClick={onClick}
      className={cn(
        "relative h-full w-64 cursor-pointer overflow-hidden rounded-lg border p-3",
        // light styles
                "border-gray-950/[.1] bg-gray-950/[.01] hover:bg-gray-950/[.03]",
        // dark styles
        "dark:border-gray-50/[.1] dark:bg-gray-50/[.10] dark:hover:bg-gray-50/[.12]"
      ,
        className
      )}
    >
      <div className="flex flex-row items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
          <Icon className="h-3.5 w-3.5 text-gray-700 dark:text-gray-200" />
        </div>
        <figcaption className="text-xs font-medium dark:text-white">
          {category}
        </figcaption>
      </div>
      <blockquote className="mt-2 text-xs">{question}</blockquote>
    </figure>
  );
};
